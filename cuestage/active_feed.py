"""Cue attive per i programmi collegati via OSC (es. Script Follower), che le mostrano nella loro interfaccia.

Il programma, dopo il suo /cuestage/client/hello, si abbona con /cuestage/client/active/subscribe e riceve
/cuestage/active con lo stato in JSON: subito, a ogni cambiamento e, mentre qualcosa suona, alla frequenza
chiesta (vedi OSC_CLIENTS.md). Con /cuestage/client/active/stop e …/pause comanda le singole cue.
"""
import json

PROTOCOL = 1
MEDIA_TYPES = ("audio", "video", "image", "pdf", "text")
MAX_BYTES = 60000          # un datagramma UDP: oltre, l'elenco si accorcia («more» = quante mancano)
IDLE_RESEND = 2.0          # senza cue attive lo stato si ripete comunque ogni tanto (programma appena collegato)


def parse_options(text):
    """«nogroups,media» -> {"nogroups": True, "media": True}."""
    return {o.strip().lower(): True for o in str(text or "").replace(";", ",").split(",") if o.strip()}


def _r(v, n=2):
    return None if v is None else round(float(v), n)


def snapshot(ctrl, show, instance="", options=None):
    """Stato delle cue attive (in attesa del pre-wait o in esecuzione), come dizionario pronto per il JSON."""
    from .ui_cuelist import list_color
    opts = options or {}

    def keep(cue):
        if opts.get("nogroups") and cue.type == "group":
            return False
        if opts.get("media") and cue.type not in MEDIA_TYPES:
            return False
        return True

    def base(cue):
        lst, _i = show.list_of(cue.id)
        d = {"id": cue.id, "number": cue.number or "", "name": cue.label(), "type": cue.type,
             "list": lst.name if lst is not None else "",
             "color": list_color(show.lists.index(lst)).name() if lst is not None else "",
             "group": cue.type == "group", "in_group": bool(cue.group)}
        return d

    cues = []
    for cue, rem in ctrl.waiting():
        if keep(cue):
            d = base(cue)
            d.update(state="wait", wait=_r(rem), elapsed=0.0, total=None, remaining=None, progress=None, status="")
            cues.append(d)
    for inst in list(ctrl.instances.values()):
        cue = inst.cue
        if inst.done or not keep(cue):
            continue
        d = base(cue)
        try:
            tot = inst.total()
        except Exception:
            tot = None
        if tot is not None and (tot != tot or tot == float("inf")):      # NaN o infinita
            tot = None
        try:
            prog = inst.progress()
        except Exception:
            prog = None
        try:
            st = inst.status_text() if hasattr(inst, "status_text") else ""
        except Exception:
            st = ""
        paused = bool(inst.paused or ctrl.paused_all)
        d.update(state="paused" if paused else "run", elapsed=_r(inst.elapsed), total=_r(tot),
                 remaining=_r(max(0.0, tot - inst.elapsed)) if tot else None,
                 progress=_r(min(1.0, max(0.0, prog)), 3) if prog is not None else None,
                 status=str(st or ""), fading=bool(getattr(inst, "_closing", False)))
        cues.append(d)
    sb = None
    try:
        lst = show.current
        i = ctrl.playhead_of(lst)
        if 0 <= i < len(lst.cues):
            c = lst.cues[i]
            sb = {"id": c.id, "number": c.number or "", "name": c.label(), "list": lst.name}
    except Exception:
        sb = None
    return {"v": PROTOCOL, "instance": instance, "paused_all": bool(ctrl.paused_all), "standby": sb,
            "cues": cues}


def encode(data):
    """JSON compatto entro MAX_BYTES (se serve si tolgono le ultime cue e si dice quante: «more»)."""
    s = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if len(s.encode()) <= MAX_BYTES:
        return s
    cues = list(data.get("cues") or [])
    total = len(cues)
    while cues:
        cues = cues[:max(0, len(cues) * 3 // 4)]
        s = json.dumps(dict(data, cues=cues, more=total - len(cues)), ensure_ascii=False, separators=(",", ":"))
        if len(s.encode()) <= MAX_BYTES:
            return s
    return json.dumps(dict(data, cues=[], more=total), separators=(",", ":"))


def structure_key(data):
    """Ciò che cambia senza il solo scorrere del tempo: cue, stati, standby (per mandare subito i cambiamenti)."""
    return json.dumps([data.get("paused_all"), data.get("standby"),
                       [(c["id"], c["state"], c.get("status"), c.get("fading")) for c in data.get("cues", [])]],
                      sort_keys=True)
