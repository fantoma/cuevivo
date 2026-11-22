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
