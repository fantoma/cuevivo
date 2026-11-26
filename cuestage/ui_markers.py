"""Elenco dei marker di una cue audio/video (scheda «Tempi e loop»): nome, tempo, note e azione.

Azioni: «Nessuna», «Recall Preset» (porta la cue in esecuzione a un suo preset, con un tempo di
transizione) e «Call Cue» (avvia un'altra cue). Le esegue il motore quando la riproduzione passa sul marker."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QToolButton, QWidget,
)

from .i18n import tr
from .model import PRESET_KINDS_FOR, TYPE_LABELS

ACTIONS = ("none", "preset", "cue", "stop", "pause", "pause_goto")


def action_labels():
    return {"none": tr("Nessuna"), "preset": tr("Recall Preset"), "cue": tr("Call Cue"), "stop": tr("Stop Cue"),
            "pause": tr("Pause Cue"), "pause_goto": tr("Pause Cue e vai al marker")}


def fmt_hms(t):
    """Tempo come «mm:ss.cc» (o «h:mm:ss.cc» oltre l'ora)."""
    t = max(0.0, float(t))
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}" if h else f"{m:02d}:{s:02d}.{cs:02d}"


class TimeSpin(QDoubleSpinBox):
    """Campo di un tempo mostrato in minuti e secondi («01:23.45»); si scrive anche «83.45», «1:23,4»,
    «0:01:23.45». Le frecce e la rotella cambiano di 0,1 s."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDecimals(3)
        self.setSingleStep(0.1)
        self.setKeyboardTracking(False)

    def textFromValue(self, v):
        return fmt_hms(v)

    def valueFromText(self, text):
        from .srt import parse_time
        t = parse_time(text)
        return float(t) if t is not None else self.value()

    def validate(self, text, pos):
        from PySide6.QtGui import QValidator
        from .srt import parse_time
        if parse_time(text) is not None:
            return QValidator.Acceptable, text, pos
        ok = all(ch.isdigit() or ch in ":.," for ch in text)
        return (QValidator.Intermediate if ok else QValidator.Invalid), text, pos


def preset_names(cue):
    return sorted({n for k in PRESET_KINDS_FOR.get(cue.type, ()) for n in cue.preset_dict(k)}, key=str.lower)


class MarkersPanel(QWidget):
    """Una riga per marker. `changed` quando l'utente modifica qualcosa (lo show è da salvare)."""
    changed = Signal()
    gotoRequested = Signal(float)       # tempo del file
    addRequested = Signal()             # «+ Marker al cursore»

    def __init__(self, cue, show_fn, parent=None):
        super().__init__(parent)
        self.cue = cue
        self.show_fn = show_fn
        self._sig = None
        self._rows = []
        from PySide6.QtWidgets import QVBoxLayout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.setSpacing(3)
        head = QHBoxLayout()
        lab = QLabel(tr("Marker"))
        lab.setStyleSheet("font-weight:bold;")
        head.addWidget(lab)
        add = QPushButton(tr("+ Marker al cursore"))
        add.setToolTip(tr("Aggiunge un marker al cursore del grafico (anche con il tasto M o con il tasto destro)"))
        add.clicked.connect(self.addRequested)
        head.addWidget(add)
        self.empty = QLabel(tr("Nessun marker: tasto destro sul grafico › «Aggiungi marker qui», oppure M."))
        self.empty.setStyleSheet("color:#888;")
        head.addWidget(self.empty)
        head.addStretch(1)
        self.head = head                # chi usa il pannello può aggiungere i suoi pulsanti a destra
        outer.addLayout(head)
        self.grid = QGridLayout()
        outer.addLayout(self.grid)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(6)
        self.grid.setVerticalSpacing(3)
        self.reload()

    def markers(self):
        if not isinstance(getattr(self.cue, "markers", None), list):
            self.cue.markers = []
        return self.cue.markers

    def _signature(self):
        return tuple(id(m) for m in self.markers())

    # ---------------------------------------------------------------- costruzione
    def _clear(self):
        while self.grid.count():
            it = self.grid.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        self._rows = []

    def reload(self):
        """Ricostruisce le righe se i marker sono cambiati (aggiunti, tolti, riordinati), altrimenti
        aggiorna solo i valori dei campi che non si stanno modificando."""
        sig = self._signature()
        if sig != self._sig:
            self._sig = sig
            self._build()
            return
        for row in self._rows:
            row["sync"]()

    def _build(self):
        self._clear()
        g = self.grid
        ms = self.markers()
        self.empty.setVisible(not ms)
        if not ms:
            return
        for col, txt in enumerate((tr("Nome"), tr("Tempo"), tr("Note"), tr("Azione"))):
            lab = QLabel(txt)
            lab.setStyleSheet("color:#999; font-size:10px;")
            g.addWidget(lab, 0, col)
        for i, m in enumerate(ms):
            self._row(i + 1, m)
        g.setColumnStretch(6, 1)

    def _row(self, r, m):
        g = self.grid
        cue = self.cue

        name = QLineEdit(str(m.get("name") or ""))
        name.setMaximumWidth(130)
        name.setPlaceholderText("M")

        def name_done():
            if name.text().strip() != str(m.get("name") or ""):
                m["name"] = name.text().strip()
                self.changed.emit()
        name.editingFinished.connect(name_done)

        tm = TimeSpin()
        tm.setRange(0, 360000)
        tm.setValue(float(m.get("t", 0)))
        tm.setToolTip(tr("Posizione nel file (minuti:secondi; si può scrivere anche in secondi, es. 83.5)"))

        def t_changed(v):
            m["t"] = round(float(v), 3)
            self.changed.emit()
        tm.valueChanged.connect(t_changed)
        go = QToolButton()
        go.setText("⌖")
        go.setToolTip(tr("Porta il cursore su questo marker"))
        go.clicked.connect(lambda: self.gotoRequested.emit(float(m.get("t", 0))))
        tw = QWidget()
        th = QHBoxLayout(tw)
        th.setContentsMargins(0, 0, 0, 0)
        th.setSpacing(2)
        th.addWidget(tm)
        th.addWidget(go)

        notes = QLineEdit(str(m.get("notes") or ""))
        notes.setPlaceholderText(tr("note"))
        notes.setMaxLength(200)
        notes.setMinimumWidth(160)
        notes.setMaximumWidth(280)

        def notes_done():
            if notes.text() != str(m.get("notes") or ""):
                m["notes"] = notes.text()
                self.changed.emit()
        notes.editingFinished.connect(notes_done)

        act = QComboBox()
        labels = action_labels()
        for k in ACTIONS:
            act.addItem(labels[k], k)
        act.setCurrentIndex(max(0, act.findData(m.get("action") or "none")))
        act.setToolTip(tr("Cosa succede quando la riproduzione arriva al marker:\n"
                          "Recall Preset: la cue va a un suo preset (audio e video) nel tempo indicato\n"
                          "Call Cue: avvia un'altra cue\n"
                          "Stop Cue: ferma questa cue (o quella scelta) con il fade indicato\n"
                          "Pause Cue: la cue si ferma qui e riparte col ▶ delle cue attive o col GO\n"
                          "Pause Cue e vai al marker: la cue si sposta al marker scelto e si ferma lì"))

        # parametri dell'azione
        pw = QWidget()
        ph = QHBoxLayout(pw)
        ph.setContentsMargins(0, 0, 0, 0)
        ph.setSpacing(4)
        pre = QComboBox()
        pre.setMinimumWidth(120)
        names = preset_names(cue)
        pre.addItem(tr("— scegli il preset —"), "")
        for n in names:
            pre.addItem(n, n)
        cur = str(m.get("preset") or "")
        if cur and cur not in names:
            pre.addItem(tr("{0} (non presente)", cur), cur)
        pre.setCurrentIndex(max(0, pre.findData(cur)))
        pre.currentIndexChanged.connect(lambda i: (m.__setitem__("preset", pre.itemData(i) or ""), self.changed.emit()))
        fade = QDoubleSpinBox()
        fade.setRange(0, 600)
        fade.setDecimals(1)
        fade.setSingleStep(0.5)
        fade.setSuffix(" s")
        fade.setKeyboardTracking(False)
        fade.setValue(float(m.get("fade", 0) or 0))
        fade.setToolTip(tr("Tempo di transizione verso il preset"))
        fade.valueChanged.connect(lambda v: (m.__setitem__("fade", round(float(v), 2)), self.changed.emit()))
        tgt = QComboBox()
        tgt.setMinimumWidth(200)

        def fill_targets():
            tgt.blockSignals(True)
            tgt.clear()
            self._fill_targets(tgt, m, this_cue=act.currentData() == "stop")
            tgt.blockSignals(False)
        tgt.currentIndexChanged.connect(lambda i: (m.__setitem__("target", tgt.itemData(i) or ""), self.changed.emit()))
        fade_lab = QLabel(tr("fade"))
        fmode = QComboBox()
        for k, txt in (("after", tr("dopo il marker")), ("before", tr("prima del marker")),
                       ("prev", tr("dal marker precedente (o IN)")), ("next", tr("fino al marker successivo (o OUT)"))):
            fmode.addItem(txt, k)
        fmode.setCurrentIndex(max(0, fmode.findData(m.get("fade_mode") or "after")))
        fmode.setToolTip(tr("Dove sta il fade rispetto al marker:\n"
                            "dopo il marker: parte dal marker e dura i secondi indicati\n"
                            "prima del marker: finisce sul marker\n"
                            "dal marker precedente: dal marker prima (o dall'IN) fino a questo\n"
                            "fino al marker successivo: da questo al marker dopo (o all'OUT)"))
        shape = QComboBox()
        from .model import FADE_SHAPE_LABELS, FADE_SHAPES
        for k in FADE_SHAPES:
            shape.addItem(FADE_SHAPE_LABELS[k], k)
        shape.setCurrentIndex(max(0, shape.findData(m.get("shape") or "scurve")))
        shape.setToolTip(tr("Forma del fade"))
        shape.currentIndexChanged.connect(lambda i: (m.__setitem__("shape", shape.itemData(i)), self.changed.emit()))
        # Pause Cue: marker di destinazione e modo di ripartire
        goto_lab = QLabel(tr("vai a"))
        goto = QComboBox()
        goto.setToolTip(tr("Marker a cui la cue si sposta prima di fermarsi"))

        def fill_goto():
            goto.blockSignals(True)
            goto.clear()
            goto.addItem(tr("— scegli il marker —"), "")
            import uuid
            for o in sorted(self.markers(), key=lambda x: float(x.get("t", 0) or 0)):
                if o is m or not isinstance(o, dict):
                    continue
                if not o.get("id"):
                    o["id"] = uuid.uuid4().hex[:10]     # i marker di destinazione si riconoscono per id
                goto.addItem(f"{o.get('name') or 'M'} · {fmt_hms(float(o.get('t', 0) or 0))}", o["id"])
            j = goto.findData(m.get("goto") or "")
            if j < 0 and m.get("goto"):
                goto.addItem(tr("⚠ marker eliminato"), m["goto"])
                j = goto.count() - 1
            goto.setCurrentIndex(max(0, j))
            goto.blockSignals(False)
        goto.currentIndexChanged.connect(lambda i: (m.__setitem__("goto", goto.itemData(i) or ""), self.changed.emit()))
        resume = QComboBox()
        resume.addItem(tr("riprende col ▶ delle cue attive"), "active")
        resume.addItem(tr("riprende col GO principale"), "go")
        resume.setCurrentIndex(max(0, resume.findData(m.get("resume") or "active")))
        resume.setToolTip(tr("Come riparte la cue ferma sul marker:\n"
                             "▶ delle cue attive: col pulsante della cue nel pannello «Cue attive»\n"
                             "GO principale: il prossimo GO fa ripartire la cue (invece di mandare la cue "
                             "successiva); mentre la cue suona il GO manda la cue successiva come sempre. "
                             "Il ▶ delle cue attive la fa ripartire in tutti e due i casi"))
        resume.currentIndexChanged.connect(lambda i: (m.__setitem__("resume", resume.itemData(i)), self.changed.emit()))
        ph.addWidget(pre)
        ph.addWidget(tgt)
        ph.addWidget(goto_lab)
        ph.addWidget(goto)
        ph.addWidget(resume)
        ph.addWidget(fade_lab)
        ph.addWidget(fmode)
        ph.addWidget(fade)
        ph.addWidget(shape)
        ph.addStretch(1)                  # parametri sempre allineati a sinistra, anche con campi nascosti

        def show_params():
            k = act.currentData()
            pre.setVisible(k == "preset")
            fade.setVisible(k in ("preset", "stop"))
            fade_lab.setVisible(k in ("preset", "stop"))
            fmode.setVisible(k in ("preset", "stop"))
            if k in ("preset", "stop"):
                # dal marker precedente / al successivo la durata è automatica: il campo resta al suo posto
                # (così le caselle non si spostano) ma disattivato, con «auto»
                auto = fmode.currentData() in ("prev", "next")
                fade.blockSignals(True)
                fade.setSpecialValueText(tr("auto") if auto else "")
                fade.setValue(0.0 if auto else float(m.get("fade", 0) or 0))
                fade.setEnabled(not auto)
                fade.blockSignals(False)
            shape.setVisible(k == "preset")         # lo stop usa la sua curva di fade
            fade.setToolTip(tr("Tempo di transizione verso il preset") if k == "preset" else
                            tr("Tempo di fade dello stop"))
            tgt.setVisible(k in ("cue", "stop"))
            if k in ("cue", "stop"):
                fill_targets()
            goto_lab.setVisible(k == "pause_goto")
            goto.setVisible(k == "pause_goto")
            if k == "pause_goto":
                fill_goto()
            resume.setVisible(k in ("pause", "pause_goto"))

        def act_changed(_i):
            k = act.currentData()
            if k == "stop" and m.get("action") == "cue":
                pass                              # la cue scelta per Call Cue resta, se c'era
            elif k == "stop":
                m["target"] = ""                  # di serie: ferma questa cue
            m["action"] = k
            show_params()
            self.changed.emit()
        act.currentIndexChanged.connect(act_changed)

        def fmode_changed(_i):
            m["fade_mode"] = fmode.currentData()
            show_params()
            self.changed.emit()
        fmode.currentIndexChanged.connect(fmode_changed)
        show_params()

        rm = QToolButton()
        rm.setText("✕")
        rm.setToolTip(tr("Elimina marker"))

        def remove():
            if m in self.markers():
                self.markers().remove(m)
            self.changed.emit()
            self.reload()
        rm.clicked.connect(remove)

        for c, w in enumerate((name, tw, notes, act, pw, rm)):
            g.addWidget(w, r, c, Qt.AlignLeft | Qt.AlignVCenter) if c == 4 else g.addWidget(w, r, c)

        def sync():
            for w, val in ((name, str(m.get("name") or "")), (notes, str(m.get("notes") or ""))):
                if not w.hasFocus() and w.text() != val:
                    w.setText(val)
            if not tm.hasFocus():
                tm.blockSignals(True)
                tm.setValue(float(m.get("t", 0)))
                tm.blockSignals(False)
        self._rows.append({"marker": m, "sync": sync})

    def _fill_targets(self, w, m, this_cue=False):
        w.addItem(tr("— questa cue —") if this_cue else tr("— scegli la cue —"), "")
        show = self.show_fn()
        cue = self.cue
        nums = {}
        for c in show.all_cues():
            n = str(c.number).strip()
            nums[n] = nums.get(n, 0) + 1
        for lst in show.lists:
            for c in lst.cues:
                if c is cue:
                    continue
                num = str(c.number).strip()
                ref = num if num and nums.get(num) == 1 else c.id
                where = "" if lst.is_main else f"[{lst.name}] "
                w.addItem(f"{where}{c.number or '·'} – {c.name or TYPE_LABELS.get(c.type, c.type)}", ref)
        cur = str(m.get("target") or "")
        i = w.findData(cur)
        if i < 0 and cur:
            tg = show.resolve_target(cur)
            if tg is not None:
                i = w.findData(tg.id)
                if i < 0:
                    i = w.findData(str(tg.number).strip())
            if i < 0:
                w.addItem(tr("{0} (non trovata)", cur), cur)
                i = w.count() - 1
        w.setCurrentIndex(max(0, i))
