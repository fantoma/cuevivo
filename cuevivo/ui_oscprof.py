"""Editor dei profili OSC (dispositivi in uscita: console luci, software…) e importazione / esportazione JSON."""
import copy
import json
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import osc_profiles as op
from .i18n import tr

PCOLS = ("id", "label", "type", "default", "min", "max", "items")


def items_to_text(items):
    """[["1", "Attiva"], ["0", "Rilascia"]] -> «1=Attiva; 0=Rilascia»."""
    return "; ".join(f"{a}={b}" for a, b in (items or []))


def text_to_items(text):
    out = []
    for part in (text or "").split(";"):
        if "=" in part:
            a, b = part.split("=", 1)
            if a.strip():
                out.append([a.strip(), b.strip()])
    return out


def _num(text):
    try:
        f = float(str(text).replace(",", "."))
        return int(f) if f == int(f) else f
    except ValueError:
        return None


class OscProfileEditor(QDialog):
    """Profilo: id, nome, porta, ricerca Art-Net, note; comandi (id, etichetta, indirizzo, argomenti, aiuto) con i
    loro parametri (id, etichetta, tipo, predefinito, minimo, massimo, voci delle scelte «valore=testo; …»)."""

    def __init__(self, parent, profile=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Profilo OSC"))
        self.resize(980, 640)
        self.p = copy.deepcopy(profile) if profile else {"id": "", "name": "", "port": 8000, "notes": "",
                                                          "commands": []}
        self.p.setdefault("commands", [])
        self.cur = -1
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.pid = QLineEdit(self.p.get("id", ""))
        self.pid.setPlaceholderText(tr("es. mia_console (lettere minuscole, cifre, _)"))
        f.addRow(tr("Id"), self.pid)
        self.name = QLineEdit(self.p.get("name", ""))
        f.addRow(tr("Nome"), self.name)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(self.p.get("port") or 8000))
        f.addRow(tr("Porta OSC predefinita"), self.port)
        drow = QHBoxLayout()
        disc = self.p.get("discover") or {}
        self.art = QCheckBox(tr("Ricerca in rete con Art-Net, nomi che contengono:"))
        self.art.setChecked(disc.get("type") == "artnet")
        self.match = QLineEdit(", ".join(disc.get("match") or []))
        self.match.setPlaceholderText(tr("es. magicq, chamsys"))
        drow.addWidget(self.art)
        drow.addWidget(self.match, 1)
        f.addRow(tr("Ricerca"), drow)
        self.notes = QPlainTextEdit(self.p.get("notes", ""))
        self.notes.setMaximumHeight(70)
        f.addRow(tr("Note"), self.notes)
        v.addLayout(f)
        sp = QSplitter(Qt.Horizontal)
        lw = QWidget()
        lv = QVBoxLayout(lw)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel(tr("Comandi")))
        self.cmds = QListWidget()
        self.cmds.currentRowChanged.connect(self._select)
        lv.addWidget(self.cmds, 1)
        br = QHBoxLayout()
        for text, fn in (("+", self._add_cmd), ("−", self._del_cmd), ("↑", lambda: self._move(-1)),
                         ("↓", lambda: self._move(1))):
            b = QPushButton(text)
            b.setFixedWidth(34)
            b.clicked.connect(fn)
            br.addWidget(b)
        br.addStretch(1)
        lv.addLayout(br)
        sp.addWidget(lw)
        rw = QWidget()
        rv = QVBoxLayout(rw)
        rv.setContentsMargins(0, 0, 0, 0)
        cf = QFormLayout()
        self.cid = QLineEdit()
        self.clabel = QLineEdit()
        self.caddr = QLineEdit()
        self.caddr.setPlaceholderText(tr("es. /pb/{pb}/go (parametri tra graffe)"))
        self.cargs = QLineEdit()
        self.cargs.setPlaceholderText(tr("es. 1   oppure   {level}   (separati da spazi)"))
        self.chelp = QLineEdit()
        for lab, w in ((tr("Id"), self.cid), (tr("Etichetta"), self.clabel), (tr("Indirizzo"), self.caddr),
                       (tr("Argomenti"), self.cargs), (tr("Aiuto"), self.chelp)):
            cf.addRow(lab, w)
            w.editingFinished.connect(self._store)
        rv.addLayout(cf)
        rv.addWidget(QLabel(tr("Parametri (tipi: int, float, enum, text; per enum le voci «valore=testo; …»)")))
        self.params = QTableWidget(0, len(PCOLS))
        self.params.setHorizontalHeaderLabels([tr("Id"), tr("Etichetta"), tr("Tipo"), tr("Predefinito"),
                                               tr("Min"), tr("Max"), tr("Voci (enum)")])
        self.params.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.params.horizontalHeader().setSectionResizeMode(len(PCOLS) - 1, QHeaderView.Stretch)
        self.params.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.params.itemChanged.connect(lambda *_: self._store())
        rv.addWidget(self.params, 1)
        pr = QHBoxLayout()
        b_add = QPushButton(tr("+ Parametro"))
        b_add.clicked.connect(self._add_param)
        b_del = QPushButton(tr("− Parametro"))
        b_del.clicked.connect(self._del_param)
        pr.addWidget(b_add)
        pr.addWidget(b_del)
        pr.addStretch(1)
        self.preview = QLabel()
        self.preview.setStyleSheet("color:#8c8;")
        pr.addWidget(self.preview)
        rv.addLayout(pr)
        sp.addWidget(rw)
        sp.setSizes([260, 700])
        v.addWidget(sp, 1)
        self.errors = QLabel()
        self.errors.setWordWrap(True)
        self.errors.setStyleSheet("color:#e66;")
        v.addWidget(self.errors)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._fill_cmds(0)

    # --- comandi
    def _fill_cmds(self, select=-1):
        self.cmds.blockSignals(True)
        self.cmds.clear()
        for c in self.p["commands"]:
            self.cmds.addItem(f"{c.get('label') or c.get('id') or '?'}")
        self.cmds.blockSignals(False)
        self.cur = -1
        if self.p["commands"]:
            self.cmds.setCurrentRow(max(0, min(select, len(self.p["commands"]) - 1)))
        else:
            self._select(-1)

    def _select(self, row):
        self._store()
        self.cur = row
        c = self.p["commands"][row] if 0 <= row < len(self.p["commands"]) else None
        for w in (self.cid, self.clabel, self.caddr, self.cargs, self.chelp, self.params):
            w.setEnabled(c is not None)
        c = c or {}
        self.cid.setText(c.get("id", ""))
        self.clabel.setText(c.get("label", ""))
        self.caddr.setText(c.get("address", ""))
        self.cargs.setText(" ".join(str(a) for a in c.get("args") or []))
        self.chelp.setText(c.get("help", ""))
        self.params.blockSignals(True)
        self.params.setRowCount(0)
        for prm in c.get("params") or []:
            self._param_row(prm)
        self.params.blockSignals(False)
        self._update_preview()

    def _param_row(self, prm):
        r = self.params.rowCount()
        self.params.insertRow(r)
        vals = [prm.get("id", ""), prm.get("label", ""), None, prm.get("default", ""),
                prm.get("min", ""), prm.get("max", ""), items_to_text(prm.get("items"))]
        for k, val in enumerate(vals):
            if k == 2:
                cb = QComboBox()
                for t in op.PARAM_TYPES:
                    cb.addItem(t)
                cb.setCurrentText(prm.get("type") or "int")
                cb.currentIndexChanged.connect(lambda *_: self._store())
                self.params.setCellWidget(r, 2, cb)
            else:
                self.params.setItem(r, k, QTableWidgetItem("" if val is None else str(val)))

    def _read_params(self):
        old = {}                                   # campi in più dei parametri (es. decimals, force_float): restano
        if 0 <= self.cur < len(self.p["commands"]):
            old = {str(x.get("id")): x for x in self.p["commands"][self.cur].get("params") or []}
        out = []
        for r in range(self.params.rowCount()):
            cell = lambda k: (self.params.item(r, k).text().strip() if self.params.item(r, k) else "")
            cb = self.params.cellWidget(r, 2)
            prm = {k: v for k, v in (old.get(cell(0)) or {}).items() if k not in ("min", "max", "items")}
            prm.update({"id": cell(0), "label": cell(1) or cell(0), "type": cb.currentText() if cb else "int"})
            d = cell(3)
            if prm["type"] in ("int", "float"):
                n = _num(d)
                prm["default"] = n if n is not None else 0
                for key, k in (("min", 4), ("max", 5)):
                    n = _num(cell(k))
                    if n is not None:
                        prm[key] = n
            else:
                prm["default"] = d
            if prm["type"] == "enum":
                prm["items"] = text_to_items(cell(6))
            out.append(prm)
        return out

    def _store(self):
        if not (0 <= self.cur < len(self.p["commands"])):
            return
        c = self.p["commands"][self.cur]
        c["id"] = self.cid.text().strip()
        c["label"] = self.clabel.text().strip()
        c["address"] = self.caddr.text().strip()
        c["args"] = self.cargs.text().split()
        if self.chelp.text().strip():
            c["help"] = self.chelp.text().strip()
        else:
            c.pop("help", None)
        c["params"] = self._read_params()
        it = self.cmds.item(self.cur)
        if it is not None:
            it.setText(c["label"] or c["id"] or "?")
        self._update_preview()

    def _update_preview(self):
        c = self.p["commands"][self.cur] if 0 <= self.cur < len(self.p["commands"]) else None
        if not c:
            self.preview.setText("")
            return
        try:
            vals = op.param_values(c, {})
            addr = c.get("address", "").format(**vals)
            args = " ".join(str(a).format(**vals) for a in c.get("args") or [])
            self.preview.setText(tr("Esempio: {0} {1}", addr, args))
        except (KeyError, IndexError, ValueError):
            self.preview.setText(tr("Esempio: —"))

    def _add_cmd(self):
        self._store()
        n = len(self.p["commands"]) + 1
        self.p["commands"].append({"id": f"cmd{n}", "label": tr("Comando {0}", n), "address": "/", "args": [],
                                   "params": []})
        self._fill_cmds(len(self.p["commands"]) - 1)

    def _del_cmd(self):
        if 0 <= self.cur < len(self.p["commands"]):
            del self.p["commands"][self.cur]
            k = self.cur
            self.cur = -1
            self._fill_cmds(k)

    def _move(self, d):
        self._store()
        i, j = self.cur, self.cur + d
        cs = self.p["commands"]
        if 0 <= i < len(cs) and 0 <= j < len(cs):
            cs[i], cs[j] = cs[j], cs[i]
            self.cur = -1
            self._fill_cmds(j)

    def _add_param(self):
        self.params.blockSignals(True)
        self._param_row({"id": f"p{self.params.rowCount() + 1}", "label": "", "type": "int", "default": 1})
        self.params.blockSignals(False)
        self._store()

    def _del_param(self):
        r = self.params.currentRow()
        if r >= 0:
            self.params.removeRow(r)
            self._store()

    # --- profilo
    def profile(self):
        """Il profilo come sta nell'editor."""
        self._store()
        p = self.p
        p["id"] = self.pid.text().strip()
        p["name"] = self.name.text().strip()
        p["port"] = self.port.value()
        p["notes"] = self.notes.toPlainText().strip()
        m = [x.strip() for x in self.match.text().split(",") if x.strip()]
        if self.art.isChecked():
            p["discover"] = {"type": "artnet", "match": m}
        else:
            p.pop("discover", None)
        return copy.deepcopy(p)

    def _save(self):
        p = self.profile()
        errs = op.validate(p)
        if errs:
            self.errors.setText("\n".join(errs))
            return
        try:
            op.save_user(p)
        except OSError as e:
            self.errors.setText(str(e))
            return
        self.accept()


class OscProfilesBox(QGroupBox):
    """Elenco dei profili OSC (forniti e dell'utente) con Nuovo, Modifica, Duplica, Elimina, Importa / Esporta
    JSON. Modificare un profilo fornito ne salva una copia dell'utente con lo stesso id (che lo sostituisce)."""

    def __init__(self, parent=None):
        super().__init__(tr("Profili OSC"), parent)
        v = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setMinimumHeight(110)
        self.list.itemDoubleClicked.connect(lambda *_: self.edit())
        v.addWidget(self.list)
        br = QHBoxLayout()
        for text, fn in ((tr("Nuovo…"), self.new), (tr("Modifica…"), self.edit), (tr("Duplica…"), self.duplicate),
                         (tr("Elimina"), self.delete), (tr("Importa JSON…"), self.import_json),
                         (tr("Esporta JSON…"), self.export_json)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())    # senza il bool di clicked (non è un percorso)
            br.addWidget(b)
        br.addStretch(1)
        v.addLayout(br)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color:#888;")
        v.addWidget(self.info)
        self.reload()

    def reload(self, select=None):
        self.list.clear()
        for pid, p in sorted(op.profiles(reload=True).items(), key=lambda x: x[1].get("name", "").lower()):
            kind = tr("fornito") if op.is_builtin(pid) else tr("tuo")
            it = QListWidgetItem(f"{p.get('name') or pid} — {pid} · {kind} · {len(p.get('commands') or [])} "
                                 + tr("comandi"))
            it.setData(Qt.UserRole, pid)
            self.list.addItem(it)
            if pid == select:
                self.list.setCurrentItem(it)
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)
        self.info.setText(tr("I profili tuoi stanno in {0}; uno con lo stesso id di un profilo fornito lo sostituisce.",
                             op.USER_DIR))

    def current(self):
        it = self.list.currentItem()
        pid = it.data(Qt.UserRole) if it else None
        return pid, (op.profiles().get(pid) if pid else None)

    def _edit(self, profile):
        d = OscProfileEditor(self, profile)
        if d.exec():
            self.reload(d.profile()["id"])
            return True
        return False

    def new(self):
        return self._edit(None)

    def edit(self):
        pid, p = self.current()
        return self._edit(p) if p else False

    def duplicate(self):
        pid, p = self.current()
        if not p:
            return False
        q = copy.deepcopy(p)
        ids = set(op.profiles())
        k = 2
        while f"{pid}_{k}" in ids:
            k += 1
        q["id"], q["name"] = f"{pid}_{k}", f"{p.get('name') or pid} ({k})"
        return self._edit(q)

    def delete(self):
        pid, p = self.current()
        if not p:
            return False
        if op.is_builtin(pid):
            QMessageBox.information(self, tr("Profili OSC"), tr("I profili forniti con Cuevivo non si eliminano."))
            return False
        if QMessageBox.question(self, tr("Profili OSC"), tr("Eliminare il profilo «{0}»?", p.get("name") or pid)) \
                != QMessageBox.Yes:
            return False
        op.delete_user(pid)
        self.reload()
        return True

    def export_json(self, path=None):
        pid, p = self.current()
        if not p:
            return None
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, tr("Esporta profilo OSC"),
                                                  os.path.join(os.path.expanduser("~"), f"{pid}.json"),
                                                  tr("Profilo OSC (*.json)"))
        if not path:
            return None
        with open(path, "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, indent=2)
            f.write("\n")
        return path

    def import_json(self, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, tr("Importa profilo OSC"), os.path.expanduser("~"),
                                                  tr("Profilo OSC (*.json)"))
        if not path:
            return None
        try:
            with open(path, encoding="utf-8") as f:
                p = json.load(f)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, tr("Profili OSC"), tr("File non valido: {0}", e))
            return None
        errs = op.validate(p) if isinstance(p, dict) else [tr("non è un profilo")]
        if errs:
            QMessageBox.warning(self, tr("Profili OSC"), tr("Profilo non valido:\n{0}", "\n".join(errs)))
            return None
        if p["id"] in op.profiles() and not getattr(self, "_overwrite_ok", False) and QMessageBox.question(
                self, tr("Profili OSC"), tr("Esiste già un profilo «{0}»: sostituirlo?", p["id"])) != QMessageBox.Yes:
            return None
        op.save_user(p)
        self.reload(p["id"])
        return p["id"]
