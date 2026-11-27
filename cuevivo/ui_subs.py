"""Sottotitoli contenuti nei file video: finestra «importa in una cue / esporta in .srt», estrazione con
avanzamento, salvataggio dei file .srt."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QLabel, QProgressDialog, QRadioButton, QVBoxLayout,
)

from . import srt
from .i18n import tr


def stream_label(st):
    bits = [srt.lang_label(st.get("lang"))]
    if st.get("title"):
        bits.append(f"«{st['title']}»")
    bits.append(st.get("codec") or "?")
    if st.get("forced"):
        bits.append(tr("forzati"))
    if st.get("default"):
        bits.append(tr("predefiniti"))
    s = f"#{int(st['n']) + 1} · " + " · ".join(bits)
    if not st.get("text"):
        s += " — " + tr("a immagine: non convertibili in testo")
    return s


class SubsFoundDialog(QDialog):
    """Il video contiene sottotitoli: quali tracce e cosa farne (cue SRT agganciata, file .srt, entrambe)."""

    def __init__(self, parent, name, streams, ask_action=True):
        super().__init__(parent)
        self.setWindowTitle(tr("Sottotitoli nel video"))
        v = QVBoxLayout(self)
        lab = QLabel(tr("«{0}» contiene {1} tracce di sottotitoli. Quali vuoi usare?", name, len(streams)))
        lab.setWordWrap(True)
        v.addWidget(lab)
        self.checks = []
        for st in streams:
            cb = QCheckBox(stream_label(st))
            cb.setEnabled(bool(st.get("text")))
            cb.setChecked(bool(st.get("text")))
            cb.setProperty("n", int(st["n"]))
            v.addWidget(cb)
            self.checks.append(cb)
        v.addSpacing(8)
        self.r_cue = QRadioButton(tr("Importa in una cue Testo SRT agganciata al video (una lingua per traccia)"))
        self.r_file = QRadioButton(tr("Esporta in file .srt accanto al video"))
        self.r_both = QRadioButton(tr("Entrambe le cose"))
        self.r_cue.setChecked(True)
        for r in (self.r_cue, self.r_file, self.r_both):
            v.addWidget(r)
            r.setVisible(ask_action)
        bb = QDialogButtonBox()
        self.ok = bb.addButton(tr("Procedi"), QDialogButtonBox.AcceptRole)
        bb.addButton(tr("Ignora"), QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        if not any(st.get("text") for st in streams):
            self.ok.setEnabled(False)
            for r in (self.r_cue, self.r_file, self.r_both):
                r.setEnabled(False)

    def result_choice(self):
        ns = [cb.property("n") for cb in self.checks if cb.isChecked() and cb.isEnabled()]
        act = "cue" if self.r_cue.isChecked() else ("file" if self.r_file.isChecked() else "both")
        return ns, act


def extract_with_progress(parent, path, ns):
    """Estrae le tracce ns dal file mostrando l'avanzamento (si può annullare). {n: testo SRT} o None."""
    dlg = QProgressDialog(tr("Estraggo i sottotitoli da «{0}»…", os.path.basename(path)), tr("Annulla"),
                          0, 0, parent)
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setMinimumDuration(400)

    def poll():
        QApplication.processEvents()
        return not dlg.wasCanceled()
    try:
        res = srt.extract_subs(path, ns, poll=poll)
        cancelled = dlg.wasCanceled()
    finally:
        dlg.reset()
        dlg.deleteLater()
    return None if cancelled else res


def export_paths(media_path, langs, folder=None):
    """Nomi dei file .srt da scrivere: «video.it.srt» accanto al video (senza sovrascrivere altri file)."""
    folder = folder or os.path.dirname(os.path.abspath(media_path))
    stem = os.path.splitext(os.path.basename(media_path))[0]
    out, used = [], set()
    for i, lg in enumerate(langs):
        base = f"{stem}.{lg}" if lg else f"{stem}.{i + 1}"
        p = os.path.join(folder, base + ".srt")
        k = 2
        while p in used or os.path.exists(p):
            p = os.path.join(folder, f"{base}-{k}.srt")
            k += 1
        used.add(p)
        out.append(p)
    return out


def write_srt(path, text):
    """Scrive un .srt in UTF-8 (riscritto pulito, numerato e in ordine)."""
    p = srt.parse(text or "")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(srt.to_srt(p) if p.entries else (text or ""))


class TimesDialog(QDialog):
    """Tempi memorizzati di una cue Testo in sequenza: modifica di tempi e frasi, esportazione in .srt,
    trasformazione in una cue di sottotitoli a tempo agganciata a una cue audio/video."""

    def __init__(self, parent, cue, show):
        from PySide6.QtWidgets import (
            QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QHeaderView, QMessageBox, QPushButton,
            QTableWidget, QTableWidgetItem,
        )
        from .model import TYPE_LABELS
        from .text_render import split_phrases
        super().__init__(parent)
        self._QFileDialog, self._QMessageBox, self._Item = QFileDialog, QMessageBox, QTableWidgetItem
        self.cue, self.sh = cue, show
        self.converted = False
        self.markers_added = False
        self.setWindowTitle(tr("Tempi e SRT — {0}", cue.label()))
        self.resize(820, 560)
        v = QVBoxLayout(self)
        ref = show.by_id(cue.text_times_ref) if cue.text_times_ref else None
        self.info = QLabel(tr("Tempi in secondi del file di «{0}»", ref.label()) if ref is not None
                           else tr("Tempi dall'avvio della cue (nessuna cue audio/video di riferimento in "
                                   "riproduzione quando sono stati memorizzati)"))
        self.info.setWordWrap(True)
        v.addWidget(self.info)
        self.tbl = QTableWidget(0, 3)
        self.tbl.setHorizontalHeaderLabels([tr("Inizio"), tr("Fine"), tr("Testo")])
        self.tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tbl.setToolTip(tr("Tempi come 00:01:02,500 o 62.5 (vuoto = non memorizzato); "
                               "nel testo « / » va a capo"))
        v.addWidget(self.tbl, 1)
        phrases = split_phrases(cue.text_content)
        times = list(cue.text_times or [])
        self.tbl.setRowCount(len(phrases))
        for r, ph in enumerate(phrases):
            tm = times[r] if r < len(times) and isinstance(times[r], (list, tuple)) and len(times[r]) == 2 \
                else [None, None]
            for col, val in enumerate(tm):
                self.tbl.setItem(r, col, QTableWidgetItem(srt.fmt_time(val) if val is not None else ""))
            self.tbl.setItem(r, 2, QTableWidgetItem(ph.replace("\n", " / ")))
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Sposta tutti i tempi di")))
        self.shift = QDoubleSpinBox()
        self.shift.setRange(-36000, 36000)
        self.shift.setDecimals(3)
        self.shift.setSingleStep(0.1)
        self.shift.setSuffix(" s")
        row.addWidget(self.shift)
        b_shift = QPushButton(tr("Applica"))
        b_shift.clicked.connect(lambda: self.shift_all(self.shift.value()))
        row.addWidget(b_shift)
        row.addStretch(1)
        b_clear = QPushButton(tr("Cancella i tempi"))
        b_clear.clicked.connect(self.clear_times)
        row.addWidget(b_clear)
        b_exp = QPushButton(tr("Esporta .srt…"))
        b_exp.clicked.connect(self.export)
        row.addWidget(b_exp)
        v.addLayout(row)
        mrow = QHBoxLayout()
        mrow.addWidget(QLabel(tr("Marker sulla cue agganciata:")))
        b_mall = QPushButton(tr("Per tutti i tempi"))
        b_mall.clicked.connect(lambda: self._markers_clicked(False))
        mrow.addWidget(b_mall)
        b_msel = QPushButton(tr("Per le righe selezionate"))
        b_msel.clicked.connect(lambda: self._markers_clicked(True))
        mrow.addWidget(b_msel)
        mrow.addStretch(1)
        self.mk_info = QLabel()
        mrow.addWidget(self.mk_info)
        v.addLayout(mrow)
        crow = QHBoxLayout()
        crow.addWidget(QLabel(tr("Agganciata a")))
        self.target = QComboBox()
        self.target.addItem(tr("— scegli la cue audio/video —"), "")
        for lst in show.lists:
            for c in lst.cues:
                if c.type in ("audio", "video"):
                    self.target.addItem(f"{lst.name} · {c.number or '·'} – {c.name or TYPE_LABELS.get(c.type, c.type)}",
                                        c.id)
        self.target.setCurrentIndex(max(0, self.target.findData(cue.text_times_ref or cue.srt_target)))
        crow.addWidget(self.target, 1)
        crow.addWidget(QLabel(tr("Lingua")))
        self.lang = QComboBox()
        self.lang.setEditable(True)
        langs = [srt.show_lang(show)] + srt.show_languages(show)
        for lg in dict.fromkeys(l for l in langs if l):
            self.lang.addItem(lg)
        self.lang.setCurrentText(srt.show_lang(show) or "")
        self.lang.setMinimumWidth(70)
        crow.addWidget(self.lang)
        b_conv = QPushButton(tr("Trasforma in sottotitoli a tempo"))
        b_conv.setToolTip(tr("La cue diventa una cue SRT agganciata alla cue scelta; il testo della sequenza "
                             "resta nella cue (tornando a «Sequenza di frasi» lo ritrovi)"))
        b_conv.clicked.connect(self._convert_clicked)
        crow.addWidget(b_conv)
        v.addLayout(crow)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    # --- dati della tabella
    def rows(self):
        """[(inizio, fine, testo)] dalla tabella (tempi None se vuoti o non validi)."""
        out = []
        for r in range(self.tbl.rowCount()):
            cell = [self.tbl.item(r, k).text() if self.tbl.item(r, k) else "" for k in range(3)]
            out.append((srt.parse_time(cell[0]), srt.parse_time(cell[1]), cell[2].replace(" / ", "\n")))
        return out

    def bad_cells(self):
        bad = []
        for r in range(self.tbl.rowCount()):
            for k in (0, 1):
                it = self.tbl.item(r, k)
                if it and it.text().strip() and srt.parse_time(it.text()) is None:
                    bad.append((r, k))
        return bad

    def shift_all(self, d):
        for r, (a, b, _t) in enumerate(self.rows()):
            for k, val in ((0, a), (1, b)):
                if val is not None:
                    self.tbl.item(r, k).setText(srt.fmt_time(max(0.0, val + d)))

    def clear_times(self):
        for r in range(self.tbl.rowCount()):
            for k in (0, 1):
                self.tbl.item(r, k).setText("")

    def srt_text(self):
        rows = self.rows()
        return srt.phrases_to_srt([t for _a, _b, t in rows], [[a, b] for a, b, _t in rows])

    def apply(self):
        """Tempi e frasi della tabella nella cue."""
        rows = self.rows()
        texts = [t for _a, _b, t in rows]
        from .text_render import split_phrases
        if texts != split_phrases(self.cue.text_content):
            self.cue.text_content = "\n\n".join(texts)
        self.cue.text_times = [[a, b] for a, b, _t in rows]
        self.sh.dirty = True

    def convert(self, target_id, lang):
        """La cue diventa una cue di sottotitoli a tempo agganciata a target_id (parte da sola con lei)."""
        self.apply()
        c = self.cue
        c.srt_tracks = [{"lang": srt.norm_lang(lang), "name": tr("dalla sequenza di frasi"), "srt": self.srt_text()}]
        c.srt_target = target_id
        c.srt_lang = ""
        c.srt_offset = 0.0
        c.srt_auto = True
        c.text_mode = "srt"
        c.trigger = "trigger"
        self.converted = True

    def export(self):
        if self.bad_cells():
            self._QMessageBox.warning(self, tr("Sottotitoli"), tr("Ci sono tempi non validi"))
            return
        text = self.srt_text()
        if not text:
            self._QMessageBox.information(self, tr("Sottotitoli"), tr("Nessuna frase ha un tempo memorizzato"))
            return
        tg = self.sh.by_id(self.target.currentData()) if self.target.currentData() else None
        base = tg.file if (tg is not None and getattr(tg, "file", "")) else os.path.join(
            os.path.expanduser("~"), self.cue.name or "sottotitoli")
        sug = export_paths(base, [srt.norm_lang(self.lang.currentText())])[0]
        path, _ = self._QFileDialog.getSaveFileName(self, tr("Esporta sottotitoli"), sug, tr("Sottotitoli (*.srt)"))
        if path:
            try:
                write_srt(path, text)
            except OSError as e:
                self._QMessageBox.warning(self, tr("Sottotitoli"), str(e))

    def add_markers(self, target_id, rows=None):
        """Marker sulla cue target_id all'inizio di ogni frase con un tempo (rows = solo quelle righe)."""
        from .text_render import BLANK
        tg = self.sh.by_id(target_id) if target_id else None
        if tg is None:
            return 0
        items = [(a, t) for r, (a, _b, t) in enumerate(self.rows())
                 if (rows is None or r in rows) and a is not None and t.strip() and t.strip() not in BLANK]
        n = srt.add_markers(tg, items)
        self.sh.dirty = True
        return n

    def _markers_clicked(self, selected):
        tid = self.target.currentData() or ""
        if not tid:
            self._QMessageBox.warning(self, tr("Sottotitoli"), tr("Scegli la cue audio/video a cui agganciare i sottotitoli"))
            return
        rows = sorted({i.row() for i in self.tbl.selectedIndexes()}) if selected else None
        if selected and not rows:
            self.mk_info.setText(tr("Seleziona prima le righe"))
            return
        n = self.add_markers(tid, rows)
        self.mk_info.setText(tr("{0} marker aggiunti", n))
        self.markers_added = True

    def _ok(self):
        if self.bad_cells():
            self._QMessageBox.warning(self, tr("Sottotitoli"), tr("Ci sono tempi non validi"))
            return
        self.apply()
        self.accept()

    def _convert_clicked(self):
        QM = self._QMessageBox
        tid = self.target.currentData() or ""
        if not tid:
            QM.warning(self, tr("Sottotitoli"), tr("Scegli la cue audio/video a cui agganciare i sottotitoli"))
            return
        if self.bad_cells():
            QM.warning(self, tr("Sottotitoli"), tr("Ci sono tempi non validi"))
            return
        if not self.srt_text():
            QM.information(self, tr("Sottotitoli"), tr("Nessuna frase ha un tempo memorizzato"))
            return
        msg = tr("La cue diventa una cue di sottotitoli a tempo agganciata a «{0}» e parte da sola con lei "
                 "(la sua partenza diventa «solo trigger»). Il testo della sequenza resta nella cue.",
                 self.target.currentText())
        if tid != (self.cue.text_times_ref or ""):
            msg += "\n\n⚠ " + tr("I tempi non sono stati memorizzati su questa cue: controllali (o spostali) "
                                 "prima di usarli.")
        if QM.question(self, tr("Sottotitoli"), msg) != QM.Yes:
            return
        self.convert(tid, self.lang.currentText())
        self.accept()
