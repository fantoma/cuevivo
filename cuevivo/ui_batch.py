"""Trova e modifica (modifiche in blocco, abilita/disabilita) e copie precedenti dello show."""
import os
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from .i18n import tr
from .model import CUE_TYPES, TYPE_LABELS


class FindEditDialog(QDialog):
    """Cue › Trova e modifica: cerca in tutto lo show (testo, tipo, lista, stato) e applica alle cue spuntate
    volume ±dB, fade, ritardo, layer, abilita / disabilita."""

    def __init__(self, mw):
        super().__init__(mw)
        self.mw = mw
        self.setWindowTitle(tr("Trova e modifica"))
        self.setModal(False)
        self.resize(900, 620)
        self.found = []
        v = QVBoxLayout(self)
        f = QHBoxLayout()
        self.text = QLineEdit()
        self.text.setPlaceholderText(tr("Cerca in numero, nome, note, file, testo…"))
        self.text.setClearButtonEnabled(True)
        f.addWidget(self.text, 2)
        self.type = QComboBox()
        self.type.addItem(tr("Tutti i tipi"), "")
        for t in list(CUE_TYPES) + ["group", "link"]:
            if t in TYPE_LABELS and self.type.findData(t) < 0:
                self.type.addItem(TYPE_LABELS[t], t)
        f.addWidget(self.type, 1)
        self.lst = QComboBox()
        f.addWidget(self.lst, 1)
        self.state = QComboBox()
        self.state.addItem(tr("Abilitate e disabilitate"), "")
        self.state.addItem(tr("Solo abilitate"), "on")
        self.state.addItem(tr("Solo disabilitate"), "off")
        f.addWidget(self.state, 1)
        v.addLayout(f)
        self.tbl = QTableWidget(0, 6)
        self.tbl.setHorizontalHeaderLabels(["✓", tr("Lista"), "#", tr("Nome"), tr("Tipo"), tr("File / testo")])
        self.tbl.verticalHeader().hide()
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        hh = self.tbl.horizontalHeader()
        for k in (0, 1, 2, 4):
            hh.setSectionResizeMode(k, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.Stretch)
        self.tbl.setToolTip(tr("Doppio clic: mostra la cue nella sua lista"))
        v.addWidget(self.tbl, 1)
        srow = QHBoxLayout()
        b_all = QPushButton(tr("Spunta tutte"))
        b_none = QPushButton(tr("Nessuna"))
        srow.addWidget(b_all)
        srow.addWidget(b_none)
        self.count = QLabel()
        srow.addWidget(self.count, 1)
        v.addLayout(srow)
        box = QGroupBox(tr("Applica alle cue spuntate"))
        g = QGridLayout(box)

        def dspin(lo, hi, step, dec, suffix, val=0.0):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setSingleStep(step)
            s.setDecimals(dec)
            s.setSuffix(suffix)
            s.setValue(val)
            return s
        self.sp_level = dspin(-60, 24, 0.5, 1, " dB")
        self.sp_level.setToolTip(tr("Si aggiunge al volume di ogni cue audio/video (negativo = abbassa)"))
        self.sp_fin = dspin(0, 600, 0.1, 2, " s")
        self.sp_fout = dspin(0, 600, 0.1, 2, " s")
        self.sp_delay = dspin(0, 36000, 0.1, 2, " s")
        self.sp_layer = QSpinBox()
        self.sp_layer.setRange(0, 99)
        rows = ((tr("Volume ±"), self.sp_level, "level"), (tr("Fade in ="), self.sp_fin, "fade_in"),
                (tr("Fade out ="), self.sp_fout, "fade_out"), (tr("Ritardo (pre-wait) ="), self.sp_delay, "delay"),
                (tr("Layer ="), self.sp_layer, "layer"))
        for i, (lab, sp, act) in enumerate(rows):
            r, c = divmod(i, 2)
            g.addWidget(QLabel(lab), r, c * 3)
            g.addWidget(sp, r, c * 3 + 1)
            b = QPushButton(tr("Applica"))
            b.clicked.connect(lambda _=False, act=act, sp=sp: self.apply(act, sp.value()))
            g.addWidget(b, r, c * 3 + 2)
        en = QPushButton(tr("Abilita"))
        dis = QPushButton(tr("Disabilita"))
        en.clicked.connect(lambda: self.apply("enable"))
        dis.clicked.connect(lambda: self.apply("disable"))
        r = (len(rows) + 1) // 2
        g.addWidget(QLabel(tr("Stato")), r, 3)
        er = QHBoxLayout()
        er.addWidget(en)
        er.addWidget(dis)
        g.addLayout(er, r, 4, 1, 2)
        self.result = QLabel()
        self.result.setStyleSheet("color:#9c9;")
        g.addWidget(self.result, r + 1, 0, 1, 6)
        v.addWidget(box)
        self.text.textChanged.connect(self.search)
        for cb in (self.type, self.lst, self.state):
            cb.currentIndexChanged.connect(self.search)
        b_all.clicked.connect(lambda: self._check_all(True))
        b_none.clicked.connect(lambda: self._check_all(False))
        self.tbl.cellDoubleClicked.connect(self._reveal)
        self.tbl.itemChanged.connect(lambda *_: self._count())
        self.search()

    def _fill_lists(self):
        cur = self.lst.currentData()
        self.lst.blockSignals(True)
        self.lst.clear()
        self.lst.addItem(tr("Tutte le liste"), "")
        for l in self.mw.show_data.lists:
            self.lst.addItem(l.name, l.id)
        self.lst.setCurrentIndex(max(0, self.lst.findData(cur)))
        self.lst.blockSignals(False)

    def matches(self):
        """[(lista, cue)] che corrispondono ai filtri."""
        sh = self.mw.show_data
        q = self.text.text().strip().lower()
        t, lid, st = self.type.currentData(), self.lst.currentData(), self.state.currentData()
        out = []
        for l in sh.lists:
            if lid and l.id != lid:
                continue
            for c in l.cues:
                ct = "link" if getattr(c, "is_link", False) else c.type
                if t and ct != t:
                    continue
                dis = sh.cue_disabled(c, l)
                if (st == "on" and dis) or (st == "off" and not dis):
                    continue
                if q:
                    hay = " ".join(str(x or "") for x in (c.number, c.name, c.notes, os.path.basename(c.file or ""),
                                                          getattr(c, "text_content", ""))).lower()
                    if q not in hay:
                        continue
                out.append((l, c))
        return out

    def search(self, *_):
        self._fill_lists()
        # le cue tolte a mano restano tolte; quelle nuove nella ricerca entrano spuntate
        self.unchecked = (getattr(self, "unchecked", set()) | {c.id for _l, c in self.found}) - \
            {c.id for c in self.checked_cues()}
        self.found = self.matches()
        sh = self.mw.show_data
        self.tbl.blockSignals(True)
        self.tbl.setRowCount(len(self.found))
        for r, (l, c) in enumerate(self.found):
            ck = QTableWidgetItem()
            ck.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            ck.setCheckState(Qt.Unchecked if c.id in self.unchecked else Qt.Checked)
            self.tbl.setItem(r, 0, ck)
            ct = "link" if getattr(c, "is_link", False) else c.type
            what = os.path.basename(c.file) if getattr(c, "file", "") else \
                (getattr(c, "text_content", "") or "").replace("\n", " / ")[:60]
            vals = [l.name, c.number or "", c.name or "", TYPE_LABELS.get(ct, ct), what]
            for k, val in enumerate(vals, 1):
                it = QTableWidgetItem(val)
                if sh.cue_disabled(c, l):
                    it.setForeground(Qt.gray)
                    f = it.font()
                    f.setStrikeOut(True)
                    it.setFont(f)
                self.tbl.setItem(r, k, it)
        self.tbl.blockSignals(False)
        self._count()

    def checked_cues(self):
        return [c for r, (_l, c) in enumerate(self.found)
                if self.tbl.item(r, 0) is not None and self.tbl.item(r, 0).checkState() == Qt.Checked]

    def _check_all(self, on):
        if on:
            self.unchecked = set()
        self.tbl.blockSignals(True)
        for r in range(self.tbl.rowCount()):
            self.tbl.item(r, 0).setCheckState(Qt.Checked if on else Qt.Unchecked)
        self.tbl.blockSignals(False)
        self._count()

    def _count(self):
        self.count.setText(tr("{0} cue trovate, {1} spuntate", len(self.found), len(self.checked_cues())))

    def _reveal(self, r, _c):
        if 0 <= r < len(self.found):
            self.mw.reveal_cue(self.found[r][1].id)

    def apply(self, action, value=None):
        cues = self.checked_cues()
        if not cues:
            self.result.setText(tr("Nessuna cue spuntata"))
            return 0
        n = self.mw.batch_apply(cues, action, value)
        self.result.setText(tr("{0} cue modificate (Ctrl+Z per annullare)", n) if n
                            else tr("Nessuna cue spuntata ha quel valore"))
        self.search()
        return n


class SnapshotsDialog(QDialog):
    """File › Copie precedenti dello show: ogni salvataggio tiene la versione sovrascritta; se ne può
    riprendere una (lo show torna com'era e resta da salvare)."""

    def __init__(self, mw):
        super().__init__(mw)
        self.mw = mw
        self.setWindowTitle(tr("Copie precedenti dello show"))
        self.resize(560, 420)
        v = QVBoxLayout(self)
        from .window.tools import SNAP_KEEP
        lab = QLabel(tr("A ogni salvataggio Cuevivo tiene una copia della versione che sovrascrive (le ultime {0}).",
                        SNAP_KEEP))
        lab.setWordWrap(True)
        v.addWidget(lab)
        self.list = QListWidget()
        v.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.b_restore = QPushButton(tr("Riprendi questa copia"))
        b_dir = QPushButton(tr("Apri la cartella"))
        b_close = QPushButton(tr("Chiudi"))
        row.addWidget(self.b_restore)
        row.addWidget(b_dir)
        row.addStretch(1)
        row.addWidget(b_close)
        v.addLayout(row)
        self.b_restore.clicked.connect(self._restore)
        self.list.itemDoubleClicked.connect(lambda *_: self._restore())
        b_dir.clicked.connect(self._open_dir)
        b_close.clicked.connect(self.close)
        self.reload()

    def reload(self):
        from .model import Show
        self.list.clear()
        for path, t in self.mw.snapshots():
            try:
                n = len(list(Show.load(path).all_cues()))
                extra = tr("{0} cue", n)
            except Exception:
                extra = "?"
            kb = max(1, os.path.getsize(path) // 1024)
            it = QListWidgetItem(f"{time.strftime('%d/%m/%Y %H:%M:%S', time.localtime(t))} · {extra} · {kb} KB")
            it.setData(Qt.UserRole, path)
            self.list.addItem(it)
        if not self.list.count():
            self.list.addItem(tr("Nessuna copia: le copie nascono dal secondo salvataggio in poi"))
            self.list.item(0).setFlags(Qt.NoItemFlags)
        self.list.setCurrentRow(0)
        self.b_restore.setEnabled(bool(self.mw.snapshots()))

    def _restore(self):
        it = self.list.currentItem()
        path = it.data(Qt.UserRole) if it is not None else None
        if path and self.mw.restore_snapshot(path):
            self.close()

    def _open_dir(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        d = self.mw.snapshot_dir(self.mw.show_data.path)
        if os.path.isdir(d):
            QDesktopServices.openUrl(QUrl.fromLocalFile(d))
