"""Sottotitoli a tempo (SRT / WebVTT) agganciati a una cue audio/video: lettura, controllo dei tempi,
lingue, tracce di sottotitoli contenute nei file video (ffprobe / ffmpeg)."""
import bisect
import functools
import os
import re
import subprocess
import tempfile

from .i18n import tr

# ------------------------------------------------------------------ lingue

LANGS = {
    "it": "Italiano", "en": "English", "sl": "Slovenščina", "de": "Deutsch", "fr": "Français",
    "es": "Español", "pt": "Português", "nl": "Nederlands", "ru": "Русский", "uk": "Українська",
    "pl": "Polski", "cs": "Čeština", "sk": "Slovenčina", "hr": "Hrvatski", "sr": "Srpski", "bs": "Bosanski",
    "hu": "Magyar", "ro": "Română", "bg": "Български", "el": "Ελληνικά", "tr": "Türkçe", "sv": "Svenska",
    "no": "Norsk", "da": "Dansk", "fi": "Suomi", "et": "Eesti", "lv": "Latviešu", "lt": "Lietuvių",
    "ca": "Català", "eu": "Euskara", "gl": "Galego", "fur": "Furlan", "he": "עברית", "ar": "العربية",
    "zh": "中文", "ja": "日本語", "ko": "한국어", "hi": "हिन्दी", "la": "Latina", "ga": "Gaeilge",
    "sq": "Shqip", "mk": "Македонски", "is": "Íslenska", "mt": "Malti",
}
# codici ISO 639-2 (quelli dei file video, es. «ita», «eng») -> codice a due lettere
ISO3 = {
    "ita": "it", "eng": "en", "slv": "sl", "deu": "de", "ger": "de", "fra": "fr", "fre": "fr", "spa": "es",
    "por": "pt", "nld": "nl", "dut": "nl", "rus": "ru", "ukr": "uk", "pol": "pl", "ces": "cs", "cze": "cs",
    "slk": "sk", "slo": "sk", "hrv": "hr", "srp": "sr", "bos": "bs", "hun": "hu", "ron": "ro", "rum": "ro",
    "bul": "bg", "ell": "el", "gre": "el", "tur": "tr", "swe": "sv", "nor": "no", "nob": "no", "dan": "da",
    "fin": "fi", "est": "et", "lav": "lv", "lit": "lt", "cat": "ca", "eus": "eu", "baq": "eu", "glg": "gl",
    "heb": "he", "ara": "ar", "zho": "zh", "chi": "zh", "jpn": "ja", "kor": "ko", "hin": "hi", "lat": "la",
    "gle": "ga", "sqi": "sq", "alb": "sq", "mkd": "mk", "mac": "mk", "isl": "is", "ice": "is", "mlt": "mt",
}


def norm_lang(code):
    """Codice di lingua normalizzato: «ITA» -> «it», «en-US» -> «en»; «und» / sconosciuto -> «»."""
    c = (code or "").strip().lower().replace("_", "-")
    if not c or c in ("und", "unk", "zxx", "mis", "mul"):
        return ""
    base = c.split("-")[0]
    if base in ISO3:
        return ISO3[base]
    return base if re.fullmatch(r"[a-z]{2,3}", base) else c


def lang_label(code):
    code = norm_lang(code)
    if not code:
        return tr("lingua ?")
    name = LANGS.get(code)
    return f"{name} ({code})" if name else code


def lang_from_name(path):
    """Lingua dal nome del file: «film.it.srt», «film_eng.srt», «film-EN.vtt» -> «it» / «en»; «» se non c'è."""
    stem = os.path.splitext(os.path.basename(path or ""))[0]
    toks = [t for t in re.split(r"[._\-\s\[\]()]+", stem) if t]
    for t in reversed(toks[1:] if len(toks) > 1 else []):
        lo = t.lower()
        if lo in LANGS or lo in ISO3:
            return norm_lang(lo)
    return ""


# ------------------------------------------------------------------ lettura

def decode(raw):
    """Byte di un file di sottotitoli -> (testo, codifica). Prova UTF-8 (con o senza BOM), UTF-16 con BOM,
    poi Windows-1252 (i vecchi .srt europei)."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace"), "utf-8"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace"), "utf-16"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("cp1252"), "cp1252"
    except UnicodeDecodeError:
        return raw.decode("latin-1"), "latin-1"


def read_file(path):
    """(testo, codifica) di un file .srt / .vtt."""
    with open(path, "rb") as f:
        return decode(f.read())


_TS = r"(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[,.](\d{1,3}))?"
_TIME_RE = re.compile(r"^\s*" + _TS + r"\s*-->\s*" + _TS + r"(?:\s.*)?$")


def _secs(h, m, s, ms):
    frac = (ms or "0")
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(frac) / (10 ** len(frac))


def fmt_time(t, sep=","):
    t = max(0.0, float(t))
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def clean_text(s):
    s = re.sub(r"\{\\[^}]*\}", "", s)            # override ASS ({\an8}, {\i1}…)
    s = re.sub(r"<[^>]+>", "", s)                 # tag <i>, <b>, <font…>, <c.giallo>…
    s = s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
    return "\n".join(l.strip() for l in s.split("\n") if l.strip())


class Parsed:
    """Sottotitoli letti da un testo SRT/VTT.
    entries: [(inizio, fine, testo, numero del blocco)] in ordine di inizio
    segments: intervalli consecutivi [(t0, t1, testo)] col testo da mostrare (le sovrapposizioni si uniscono)
    issues: [(gravità «error»/«warn», codice, blocchi, dettaglio)] problemi del file in sé"""

    def __init__(self, entries, issues):
        self.entries = entries
        self.issues = issues
        self.segments = _segments(entries)
        self._starts = [s[0] for s in self.segments]

    def text_at(self, t):
        """Testo visibile al tempo t («» se nessun sottotitolo)."""
        k = bisect.bisect_right(self._starts, t) - 1
        if k >= 0:
            t0, t1, txt = self.segments[k]
            if t < t1:
                return txt
        return ""

    def index_at(self, t):
        """Numero (da 1) dell'ultimo sottotitolo iniziato al tempo t, 0 prima del primo."""
        return bisect.bisect_right([e[0] for e in self.entries], t)

    def last_end(self):
        return max((e[1] for e in self.entries), default=0.0)


def _segments(entries):
    pts = sorted({e[0] for e in entries} | {e[1] for e in entries})
    out = []
    active = []
    i = 0
    for a, b in zip(pts, pts[1:]):
        while i < len(entries) and entries[i][0] <= a:
            active.append(entries[i])
            i += 1
        active = [e for e in active if e[1] > a]
        if active:
            txt = "\n".join(e[2] for e in active)
            if out and out[-1][1] == a and out[-1][2] == txt:
                out[-1] = (out[-1][0], b, txt)
            else:
                out.append((a, b, txt))
    return out


def _blocks(nums, limit=6):
    s = ", ".join(str(n) for n in nums[:limit])
    return s + (" …" if len(nums) > limit else "")


@functools.lru_cache(maxsize=64)
def parse(text):
    """Testo SRT o WebVTT -> Parsed (il risultato è condiviso: non modificarlo)."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    entries, bad_syntax, bad_end, empty, bad_num, unordered, overlap, short = [], [], [], [], [], [], [], []
    vtt = text.lstrip().startswith("WEBVTT")
    k = 0
    prev_num = 0
    for block in re.split(r"\n[ \t]*\n", text.strip("\n")):
        lines = block.split("\n")
        while lines and not lines[0].strip():
            lines.pop(0)
        if not lines:
            continue
        if vtt and (lines[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION"))):
            continue
        k += 1
        num = None
        ti = next((i for i, l in enumerate(lines[:3]) if "-->" in l), None)
        if ti is not None and ti > 0 and re.fullmatch(r"\s*\d+\s*", lines[ti - 1]):
            num = int(lines[ti - 1])
        label = num if num is not None else k
        if num is not None and not vtt:
            if num != prev_num + 1:
                bad_num.append(num)
            prev_num = num
        m = _TIME_RE.match(lines[ti]) if ti is not None else None
        if m is None:
            bad_syntax.append(label)
            continue
        g = m.groups()
        t0, t1 = _secs(*g[0:4]), _secs(*g[4:8])
        txt = clean_text("\n".join(lines[ti + 1:]))
        if t1 <= t0:
            bad_end.append(label)
            continue
        if not txt:
            empty.append(label)
            continue
        if entries and t0 < entries[-1][0]:
            unordered.append(label)
        if t1 - t0 < 0.3:
            short.append(label)
        entries.append((t0, t1, txt, label))
    entries.sort(key=lambda e: (e[0], e[1]))
    for a, b in zip(entries, entries[1:]):
        if b[0] < a[1] - 0.0005:
            overlap.append(b[3])
    issues = []
    if not entries and not bad_syntax:
        issues.append(("error", "none", [], ""))
    if bad_syntax:
        issues.append(("error", "syntax", bad_syntax, ""))
    if bad_end:
        issues.append(("error", "end_before", bad_end, ""))
    if unordered:
        issues.append(("warn", "order", unordered, ""))
    if overlap:
        issues.append(("warn", "overlap", overlap, ""))
    if short:
        issues.append(("warn", "short", short, ""))
    if empty:
        issues.append(("warn", "empty", empty, ""))
    if bad_num:
        issues.append(("warn", "numbering", bad_num, ""))
    return Parsed(entries, issues)


FPS_RATIOS = ((25 / 23.976, "23,976 → 25"), (23.976 / 25, "25 → 23,976"),
              (30 / 25, "25 → 30"), (25 / 30, "30 → 25"), (25 / 24, "24 → 25"), (24 / 25, "25 → 24"))


def check_media(parsed, duration, start=0.0, end=0.0, offset=0.0):
    """Controllo dei tempi rispetto al file della cue bersaglio: durata del file, punti IN/OUT, ritardo.
    Restituisce altri problemi nello stesso formato di Parsed.issues."""
    issues = []
    es = [(e[0] + offset, e[1] + offset, e[3]) for e in parsed.entries]
    if not es:
        return issues
    if duration and duration > 0:
        beyond = [n for a, b, n in es if a >= duration]
        tail = [n for a, b, n in es if a < duration < b - 0.05]
        if beyond:
            issues.append(("error", "beyond", beyond, fmt_time(duration)))
        if tail:
            issues.append(("warn", "tail", tail, fmt_time(duration)))
        last = max(b for a, b, n in es)
        if beyond:
            # tempi «stirati» di un rapporto tipico tra frame rate: file per un'altra versione del video
            ratio = last / duration
            for r, lab in FPS_RATIOS:
                if abs(ratio - r) < 0.015:
                    issues.append(("warn", "fps", [], lab))
                    break
        elif last < duration * 0.5 and duration > 60:
            issues.append(("warn", "early", [], fmt_time(last)))
    if start and start > 0:
        before = [n for a, b, n in es if b <= start]
        if before:
            issues.append(("warn", "before_in", before, fmt_time(start)))
    if end and end > 0:
        after = [n for a, b, n in es if a >= end and not (duration and a >= duration)]
        if after:
            issues.append(("warn", "after_out", after, fmt_time(end)))
    if any(a < 0 for a, b, n in es):
        issues.append(("warn", "negative", [n for a, b, n in es if a < 0], ""))
    return issues


def issue_text(issue):
    sev, code, nums, det = issue
    b = _blocks(nums)
    n = len(nums)
    msg = {
        "none": lambda: tr("Nessun sottotitolo trovato nel file"),
        "syntax": lambda: tr("{0} blocchi senza tempi validi (scartati): {1}", n, b),
        "end_before": lambda: tr("{0} sottotitoli finiscono prima di iniziare (scartati): {1}", n, b),
        "order": lambda: tr("{0} sottotitoli fuori ordine (riordinati): {1}", n, b),
        "overlap": lambda: tr("{0} sottotitoli si sovrappongono al precedente (mostrati insieme): {1}", n, b),
        "short": lambda: tr("{0} sottotitoli durano meno di 0,3 s: {1}", n, b),
        "empty": lambda: tr("{0} sottotitoli senza testo (scartati): {1}", n, b),
        "numbering": lambda: tr("Numerazione non progressiva ai blocchi {0}", b),
        "beyond": lambda: tr("{0} sottotitoli iniziano dopo la fine del file ({1}): non compariranno: {2}", n, det, b),
        "tail": lambda: tr("{0} sottotitoli finiscono dopo la fine del file ({1}): {2}", n, det, b),
        "fps": lambda: tr("I tempi sembrano di un video a un'altra velocità ({0} fps): controlla la versione del file", det),
        "early": lambda: tr("L'ultimo sottotitolo finisce a {0}, prima di metà del file: è il file giusto?", det),
        "before_in": lambda: tr("{0} sottotitoli finiscono prima del punto IN ({1}): non compariranno", n, det),
        "after_out": lambda: tr("{0} sottotitoli iniziano dopo il punto OUT ({1}): non compariranno", n, det),
        "negative": lambda: tr("Con il ritardo impostato {0} sottotitoli iniziano prima di zero", n),
        "encoding": lambda: tr("Il file non è in UTF-8: letto come {0}, controlla le lettere accentate", det),
    }.get(code)
    return ("✘ " if sev == "error" else "⚠ ") + (msg() if msg else code)


def to_srt(parsed):
    """Testo SRT pulito (numerato, in ordine) dei sottotitoli letti."""
    out = []
    for i, (a, b, txt, _n) in enumerate(parsed.entries, 1):
        out.append(f"{i}\n{fmt_time(a)} --> {fmt_time(b)}\n{txt}\n")
    return "\n".join(out)


def parse_time(s):
    """«00:01:02,500», «1:02.5», «62.5» -> secondi; None se non è un tempo."""
    s = (s or "").strip().replace(",", ".")
    if not s:
        return None
    try:
        parts = [float(x) for x in s.split(":")]
    except ValueError:
        return None
    if len(parts) > 3 or any(x < 0 for x in parts):
        return None
    t = 0.0
    for x in parts:
        t = t * 60 + x
    return t


def phrases_to_srt(phrases, times, default=3.0):
    """Frasi di una cue in sequenza con i tempi memorizzati [[inizio, fine], …] -> testo SRT. Le frasi senza
    inizio e quelle vuote («_») si saltano; una fine mancante è l'inizio della frase seguente (al massimo
    «default» secondi dopo)."""
    from .text_render import BLANK
    items = []
    for i, ph in enumerate(phrases):
        tm = times[i] if i < len(times) and isinstance(times[i], (list, tuple)) else None
        if not tm or tm[0] is None:
            continue
        items.append((float(tm[0]), tm[1] if len(tm) > 1 else None, ph))
    items.sort(key=lambda x: x[0])
    out = []
    for k, (a, b, ph) in enumerate(items):
        nxt = items[k + 1][0] if k + 1 < len(items) else None
        if b is None or b <= a:
            b = min(a + default, nxt) if (nxt is not None and nxt > a) else a + default
        if not ph.strip() or ph.strip() in BLANK:
            continue
        out.append((a, float(b), ph.strip("\n")))
    return "\n".join(f"{i}\n{fmt_time(a)} --> {fmt_time(b)}\n{t}\n" for i, (a, b, t) in enumerate(out, 1))


def add_markers(target, items):
    """Marker sulla cue audio/video per i tempi dei sottotitoli: items = [(secondi del file, testo)].
    Non si duplicano quelli già presenti allo stesso tempo con lo stesso nome. Restituisce quanti ne aggiunge."""
    ms = [dict(m) for m in (target.markers or []) if isinstance(m, dict)]
    n = 0
    for t, text in items:
        if t is None or t < 0:
            continue
        name = " ".join((text or "").split())
        name = name if len(name) <= 40 else name[:39] + "…"
        if any(abs(float(m.get("t", -1)) - t) < 0.01 and m.get("name") == name for m in ms):
            continue
        ms.append({"t": round(float(t), 3), "name": name})
        n += 1
    ms.sort(key=lambda m: float(m.get("t", 0)))
    target.markers = ms
    return n


# ------------------------------------------------------------------ cue

def make_track(path):
    """Traccia di una cue SRT da un file: il testo viene salvato nello show (lo show resta autonomo)."""
    text, enc = read_file(path)
    tr_ = {"lang": lang_from_name(path), "name": os.path.basename(path), "srt": text}
    if enc not in ("utf-8", "utf-16"):
        tr_["encoding"] = enc
    return tr_


def track_issues(track):
    p = parse(track.get("srt") or "")
    iss = list(p.issues)
    if track.get("encoding"):
        iss.append(("warn", "encoding", [], track["encoding"]))
    return iss


# lingua scelta su questa istanza (menu Uscita video, salvata nelle preferenze del computer): vale al posto
# della lingua dello show, così ogni slave può mostrare i sottotitoli nella sua lingua
_local = {"lang": ""}


def set_local_lang(code):
    _local["lang"] = norm_lang(code)


def local_lang():
    return _local["lang"]


def show_lang(show):
    return norm_lang((getattr(show, "settings", None) or {}).get("sub_lang", "")) if show is not None else ""


def pick_track(cue, show=None):
    """Traccia della lingua scelta: quella della cue, altrimenti quella di questa istanza, altrimenti la lingua
    dello show; se non c'è, la prima."""
    tracks = [t for t in (cue.srt_tracks or []) if isinstance(t, dict)]
    if not tracks:
        return None
    want = norm_lang(cue.srt_lang) or local_lang() or show_lang(show)
    if want:
        for t in tracks:
            if norm_lang(t.get("lang")) == want:
                return t
    return tracks[0]


def show_languages(show):
    """Lingue presenti nelle cue SRT dello show (nell'ordine in cui compaiono)."""
    out = []
    for c in show.all_cues() if show is not None else []:
        if getattr(c, "type", "") == "text" and getattr(c, "text_mode", "") == "srt":
            for t in c.srt_tracks or []:
                lg = norm_lang(t.get("lang")) if isinstance(t, dict) else ""
                if lg and lg not in out:
                    out.append(lg)
    return out


def media_targets(show):
    """Cue che possono reggere i sottotitoli: audio e video (anche collegamenti) con un file."""
    return [c for c in show.all_cues() if getattr(c, "type", "") in ("audio", "video")]


def target_info(show, cue, loader=None):
    """(cue bersaglio, durata del file, IN, OUT) della cue SRT."""
    tg = show.by_id(cue.srt_target) if (show is not None and cue.srt_target) else None
    if tg is None:
        return None, 0.0, 0.0, 0.0
    dur = 0.0
    if loader is not None and getattr(tg, "file", ""):
        dur = float((loader.info.get(tg.file) or {}).get("duration") or 0)
    return tg, dur, float(tg.start or 0), float(tg.end or 0) if (tg.end and tg.end > 0) else 0.0


def all_issues(show, cue, track, loader=None):
    iss = track_issues(track)
    tg, dur, a, b = target_info(show, cue, loader)
    if tg is not None:
        iss += check_media(parse(track.get("srt") or ""), dur, a, b, float(cue.srt_offset or 0))
    return iss


# ------------------------------------------------------------------ sottotitoli nei file video

TEXT_CODECS = {"subrip", "srt", "mov_text", "ass", "ssa", "webvtt", "text", "subviewer", "subviewer1",
               "microdvd", "sami", "realtext", "jacosub", "mpl2", "pjs", "stl", "vplayer", "eia_608"}


def probe_subs(path):
    """Tracce di sottotitoli di un file: [{n, index, codec, lang, title, text, forced, default}]
    (n = numero tra i soli sottotitoli, per «-map 0:s:n»; text = False per quelli a immagine, non leggibili)."""
    import json
    from .media import FFPROBE
    from .system import subprocess_flags
    if not FFPROBE or not path or not os.path.isfile(path):
        return []
    try:
        p = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "s", "-print_format", "json",
                            "-show_streams", path], capture_output=True, timeout=20, check=False,
                           **subprocess_flags())
        data = json.loads(p.stdout or b"{}")
    except Exception:
        return []
    out = []
    for n, st in enumerate(data.get("streams", [])):
        tags = {k.lower(): v for k, v in (st.get("tags") or {}).items()}
        disp = st.get("disposition") or {}
        codec = st.get("codec_name") or "?"
        out.append({"n": n, "index": st.get("index", n), "codec": codec,
                    "lang": norm_lang(tags.get("language", "")), "title": tags.get("title", ""),
                    "text": codec in TEXT_CODECS, "forced": bool(disp.get("forced")),
                    "default": bool(disp.get("default"))})
    return out


def extract_subs(path, ns, poll=None):
    """Estrae in SRT le tracce di sottotitoli ns (numeri n di probe_subs) con una sola lettura del file.
    poll(): chiamata spesso durante l'estrazione, se restituisce False interrompe.
    Restituisce {n: testo SRT}; solleva RuntimeError se ffmpeg fallisce."""
    from .media import FFMPEG
    from .system import subprocess_flags
    if not FFMPEG:
        raise RuntimeError(tr("ffmpeg non trovato"))
    ns = list(ns)
    if not ns:
        return {}
    tmp = tempfile.mkdtemp(prefix="cuevivo-subs-")
    outs = {n: os.path.join(tmp, f"s{n}.srt") for n in ns}
    cmd = [FFMPEG, "-v", "error", "-nostdin", "-y", "-i", path]
    for n in ns:
        cmd += ["-map", f"0:s:{n}", "-c:s", "srt", outs[n]]
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **subprocess_flags())
        while True:
            try:
                p.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                if poll is not None and poll() is False:
                    p.kill()
                    p.wait()
                    return {}
        err = p.stderr.read().decode(errors="replace").strip() if p.stderr else ""
        res = {}
        for n, f in outs.items():
            if os.path.isfile(f) and os.path.getsize(f) > 0:
                res[n] = read_file(f)[0]
        if p.returncode != 0 and not res:
            raise RuntimeError(err[:300] or tr("ffmpeg uscita {0}", p.returncode))
        return res
    finally:
        for f in outs.values():
            try:
                os.remove(f)
            except OSError:
                pass
        try:
            os.rmdir(tmp)
        except OSError:
            pass
