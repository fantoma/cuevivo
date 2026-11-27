"""Pannello «Cue attive» (dimensione, filtri, finestra separata), Trova e modifica, cue sheet, copie precedenti
dello show (parte di MainWindow)."""
import csv
import hashlib
import html
import os
import shutil
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QScrollArea, QToolButton, QVBoxLayout, QWidget,
)

from ..i18n import tr

SNAP_KEEP = 30            # copie precedenti conservate per ogni show


class _ActiveWindow(QWidget):
    """Finestra separata con le cue attive (per esempio sul secondo monitor): chiudendola il pannello torna
    al suo posto nella finestra principale."""

    def __init__(self, mw):
        super().__init__(None, Qt.Window)
        from ..ui_cuelist import ActivePanel
        self.mw = mw
        self.setWindowTitle(tr("Cue attive"))
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        v.addLayout(mw._active_header(floating=True))
        self.panel = ActivePanel(mw.ctrl)
        mw._wire_active(self.panel)
        sa = QScrollArea()
        sa.setWidget(self.panel)
        sa.setWidgetResizable(True)
        v.addWidget(sa, 1)
        self.resize(480, 640)

    def closeEvent(self, e):
        self.mw.qs.setValue("active_geometry", self.saveGeometry())
        super().closeEvent(e)
        if not getattr(self.mw, "_closing_active", False):
            self.mw.dock_active()


class ToolsMixin:
    # ------------------------------------------------------------------ cue attive
    def _wire_active(self, panel):
        panel.stopRequested.connect(
            lambda cid: self.ctrl.stop_cue(cid, float(self.show_data.settings.get("stop_fade", 0.3))))
        panel.pauseRequested.connect(self._toggle_pause_cue)
        panel.showCueRequested.connect(self.reveal_cue)
        panel.set_view(*self._active_view())

    def _active_view(self):
        from ..ui_cuelist import ActivePanel
        try:
            k = int(self.qs.value("active_scale", 1))
        except (TypeError, ValueError):
            k = 1
        k = max(0, min(len(ActivePanel.SCALES) - 1, k))
        b = lambda key: str(self.qs.value(key, "false")).lower() in ("true", "1")
        return ActivePanel.SCALES[k], b("active_hide_groups"), b("active_only_media")

    def _active_header(self, floating=False):
        """Titolo «Cue attive» con il menu ⚙ (dimensione, filtri) e il pulsante per staccarlo / riagganciarlo."""
        from ..ui_cuelist import ActivePanel
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel(tr("Cue attive")))
        row.addStretch(1)
        opt = QToolButton()
        opt.setText("⚙")
        opt.setToolTip(tr("Dimensione delle righe e filtri delle cue attive"))
        opt.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(opt)
        sm = m.addMenu(tr("Dimensione delle righe"))
        names = (tr("Compatta"), tr("Normale"), tr("Grande"), tr("Molto grande"))

        def fill():
            sm.clear()
            cur, hg, om = self._active_view()
            for i, (sc, name) in enumerate(zip(ActivePanel.SCALES, names)):
                a = sm.addAction(name)
                a.setCheckable(True)
                a.setChecked(abs(sc - cur) < 1e-6)
                a.triggered.connect(lambda _=False, i=i: self.set_active_view(scale_index=i))
            a_g.setChecked(hg)
            a_m.setChecked(om)
        a_g = m.addAction(tr("Nascondi i gruppi"))
        a_g.setCheckable(True)
        a_g.toggled.connect(lambda on: self.set_active_view(hide_groups=on))
        a_m = m.addAction(tr("Solo audio, video, immagini, PDF e testi"))
        a_m.setCheckable(True)
        a_m.toggled.connect(lambda on: self.set_active_view(only_media=on))
        m.aboutToShow.connect(fill)
        opt.setMenu(m)
        row.addWidget(opt)
        det = QToolButton()
        det.setText("⧉")
        if floating:
            det.setToolTip(tr("Riaggancia le cue attive alla finestra principale"))
            det.clicked.connect(self.dock_active)
        else:
            det.setToolTip(tr("Stacca le cue attive in una finestra separata (es. sul secondo monitor)"))
            det.clicked.connect(self.float_active)
        row.addWidget(det)
        return row

    def set_active_view(self, scale_index=None, hide_groups=None, only_media=None):
        if scale_index is not None:
            self.qs.setValue("active_scale", int(scale_index))
        if hide_groups is not None:
            self.qs.setValue("active_hide_groups", bool(hide_groups))
        if only_media is not None:
            self.qs.setValue("active_only_media", bool(only_media))
        view = self._active_view()
        for p in self._active_panels():
            p.set_view(*view)

    def _active_panels(self):
        out = [self.active]
        w = getattr(self, "active_window", None)
        if w is not None:
            out.append(w.panel)
        return out

    def float_active(self):
        """Le cue attive in una finestra separata; al loro posto resta un avviso per riagganciarle."""
        if getattr(self, "active_window", None) is not None:
            self.active_window.raise_()
            return self.active_window
        w = self.active_window = _ActiveWindow(self)
        g = self.qs.value("active_geometry")
        if g is not None:
            w.restoreGeometry(g)
        self.active_dock.hide()
        self.active_placeholder.show()
        self.qs.setValue("active_floating", True)
        w.show()
        return w

    def dock_active(self):
        w = getattr(self, "active_window", None)
        self.active_window = None
        if w is not None:
            self._closing_active = True
            try:
                self.qs.setValue("active_geometry", w.saveGeometry())
                w.close()
                w.deleteLater()
            finally:
                self._closing_active = False
        self.active_placeholder.hide()
        self.active_dock.show()
        self.qs.setValue("active_floating", False)

    def _build_active_area(self, layout):
        """Pannello «Cue attive» nella finestra principale (con il posto per quando è staccato)."""
        from ..ui_cuelist import ActivePanel
        self.active_dock = QWidget()
        v = QVBoxLayout(self.active_dock)
        v.setContentsMargins(0, 0, 0, 0)
        v.addLayout(self._active_header())
        self.active = ActivePanel(self.ctrl)
        self._wire_active(self.active)
        sa = QScrollArea()
        sa.setWidget(self.active)
        sa.setWidgetResizable(True)
        v.addWidget(sa, 1)
        layout.addWidget(self.active_dock, 2)
        self.active_placeholder = QLabel(tr("Cue attive in una finestra separata — <a href='dock'>riaggancia</a>"))
        self.active_placeholder.setStyleSheet("color:#999;")
        self.active_placeholder.linkActivated.connect(lambda _l: self.dock_active())
        self.active_placeholder.hide()
        layout.addWidget(self.active_placeholder)

    # ------------------------------------------------------------------ trova e modifica
    def find_edit_dialog(self):
        """Cue › Trova e modifica…: cerca cue in tutto lo show e le modifica in blocco."""
        from ..ui_batch import FindEditDialog
        d = getattr(self, "_find_dlg", None)
        if d is None or d.mw is not self:
            d = self._find_dlg = FindEditDialog(self)
        else:
            d.search()
        d.show()
        d.raise_()
        d.activateWindow()
        return d

    def batch_apply(self, cues, action, value=None):
        """Modifica in blocco. action: «level» (±dB), «fade_in» / «fade_out» / «delay» (secondi), «layer»,
        «enable», «disable». Restituisce quante cue sono cambiate."""
        from ..model import MIN_DB
        n = 0
        for c in cues:
            link = getattr(c, "is_link", False)
            if action in ("enable", "disable"):
                on = action == "disable"
                if bool(c.disabled) != on:
                    c.disabled = on
                    n += 1
                continue
            if link or c.type == "group":
                continue                       # un collegamento ha i valori dell'originale
            if action == "level" and c.type in ("audio", "video"):
                c.level_db = round(max(MIN_DB, min(24.0, float(c.level_db or 0) + float(value))), 2)
                n += 1
            elif action in ("fade_in", "fade_out") and c.type in ("audio", "video", "image", "pdf"):
                setattr(c, action, max(0.0, float(value)))
                if c.type == "video" and getattr(c, "fade_link", True):
                    setattr(c, "v_" + action, max(0.0, float(value)))
                n += 1
            elif action == "delay":
                c.delay = max(0.0, float(value))
                n += 1
            elif action == "layer" and c.type in ("video", "image", "pdf", "text"):
                c.layer = int(value)
                n += 1
        if n:
            labels = {"level": tr("volume"), "fade_in": "fade in", "fade_out": "fade out", "delay": tr("ritardo"),
                      "layer": "layer", "enable": tr("abilita"), "disable": tr("disabilita")}
            self.show_data.dirty = True
            if action in ("enable", "disable"):
                self._normalize_stingers()
                self._refresh_disabled()
            self.model.beginResetModel()
            self.model.endResetModel()
            self._history_capture(tr("Modifica in blocco ({0}): {1} cue", labels.get(action, action), n))
            self.inspector.refresh_fields()
            self.ctrl.changed.emit()
        return n

    # ------------------------------------------------------------------ cue sheet
    def cue_sheet_rows(self):
        """Righe del cue sheet di tutte le liste: [(lista, [valori delle colonne])], intestazioni comprese."""
        from ..ui_cuelist import C_DELAY, C_DUR, C_NAME, C_NUM, C_TARGET, C_TRIG, C_TYPE
        from ..media import fmt_time
        sh, m = self.show_data, self.model
        cols = (C_NUM, C_TYPE, C_NAME, C_TARGET, C_DELAY, C_DUR, C_TRIG)
        head = [m.headerData(c, Qt.Horizontal, Qt.DisplayRole) or "" for c in cols]
        head += [tr("Note"), tr("Marker"), tr("Disabilitata")]
        out = []
        old = sh.view
        try:
            for i, lst in enumerate(sh.lists):
                sh.view = i
                rows = []
                for r, c in enumerate(lst.cues):
                    vals = []
                    for col in cols:
                        v = m.data(m.index(r, col), Qt.DisplayRole)
                        vals.append("" if v is None else str(v))
                    if c.group and c.type != "group":
                        vals[2] = "    " + vals[2]            # cue di un gruppo: rientrata
                    mk = ", ".join(f"{fmt_time(float(x.get('t', 0)))} {x.get('name') or ''}".strip()
                                   for x in (getattr(c, "markers", None) or []) if isinstance(x, dict))
                    vals += [(c.notes or "").replace("\r", ""), mk,
                             "✕" if sh.cue_disabled(c, lst) else ""]
                    rows.append(vals)
                out.append((lst, rows))
        finally:
            sh.view = old
        return head, out

    def export_cue_sheet(self, path=None):
        """File › Esporta cue sheet: CSV (separatore «;», per Excel/LibreOffice) o PDF da stampare."""
        if path is None:
            base = os.path.splitext(self.show_data.path or os.path.join(os.path.expanduser("~"), "show"))[0]
            path, flt = QFileDialog.getSaveFileName(self, tr("Esporta cue sheet"), base + " - cue sheet.pdf",
                                                    tr("PDF (*.pdf);;CSV (*.csv)"))
            if not path:
                return None
            if not os.path.splitext(path)[1]:
                path += ".csv" if "csv" in flt.lower() else ".pdf"
        head, lists = self.cue_sheet_rows()
        try:
            if path.lower().endswith(".csv"):
                with open(path, "w", encoding="utf-8-sig", newline="") as f:
                    w = csv.writer(f, delimiter=";")
                    w.writerow([tr("Lista")] + head)
                    for lst, rows in lists:
                        for r in rows:
                            w.writerow([lst.name] + r)
            else:
                self._cue_sheet_pdf(path, head, lists)
        except OSError as e:
            QMessageBox.warning(self, tr("Esporta cue sheet"), str(e))
            return None
        self.status(tr("Cue sheet esportato: {0}", path))
        return path

    def _cue_sheet_pdf(self, path, head, lists):
        from PySide6.QtCore import QMarginsF
        from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument
        sh = self.show_data
        title = os.path.splitext(os.path.basename(sh.path))[0] if sh.path else tr("show senza titolo")
        ver = sh.active.name if len(getattr(sh, "versions", []) or []) > 1 else ""
        e = html.escape
        parts = [f"<h2>{e(title)}{' — ' + e(ver) if ver else ''}</h2>",
                 f"<p style='color:#666'>{e(tr('Cue sheet del {0}', time.strftime('%d/%m/%Y %H:%M')))}</p>"]
        for lst, rows in lists:
            if not rows:
                continue
            parts.append(f"<h3>{e(lst.name)}</h3><table border='1' cellspacing='0' cellpadding='3' width='100%'"
                         " style='border-collapse:collapse;font-size:8pt'><tr>"
                         + "".join(f"<th style='background:#ddd'>{e(h)}</th>" for h in head) + "</tr>")
            for r in rows:
                grey = " style='color:#999'" if r[-1] else ""
                parts.append(f"<tr{grey}>" + "".join(
                    f"<td>{e(v).replace(chr(10), '<br>').replace('    ', '&nbsp;&nbsp;&nbsp;&nbsp;')}</td>"
                    for v in r) + "</tr>")
            parts.append("</table>")
        doc = QTextDocument()
        doc.setHtml("".join(parts))
        pw = QPdfWriter(path)
        pw.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Landscape, QMarginsF(10, 10, 10, 10),
                                     QPageLayout.Millimeter))
        pw.setTitle(title)
        doc.setPageSize(pw.pageLayout().paintRectPixels(pw.resolution()).size().toSizeF())
        doc.print_(pw)

    # ------------------------------------------------------------------ copie precedenti
    @staticmethod
    def snapshot_dir(show_path):
        """Cartella delle copie precedenti: «.nome.cueshow.snapshots» accanto allo show (se non si può scrivere
        lì, nella cartella dei dati del programma)."""
        d = os.path.join(os.path.dirname(os.path.abspath(show_path)),
                         "." + os.path.basename(show_path) + ".snapshots")
        if os.access(os.path.dirname(d), os.W_OK):
            return d
        from ..appinfo import data_base
        h = hashlib.sha1(os.path.abspath(show_path).encode()).hexdigest()[:10]
        return os.path.join(data_base(), "snapshots", f"{os.path.basename(show_path)}-{h}")

    def snapshots(self, show_path=None):
        """[(percorso, data)] delle copie precedenti, dalla più recente."""
        p = show_path or self.show_data.path
        if not p:
            return []
        d = self.snapshot_dir(p)
        try:
            names = [n for n in os.listdir(d) if n.endswith(".cueshow")]
        except OSError:
            return []
        out = [(os.path.join(d, n), os.path.getmtime(os.path.join(d, n))) for n in names]
        return sorted(out, key=lambda x: (x[1], x[0]), reverse=True)

    def _snapshot_before_save(self, path):
        """Prima di sovrascrivere lo show se ne tiene una copia datata (le ultime SNAP_KEEP; una copia uguale
        all'ultima non si ripete)."""
        if not path or not os.path.isfile(path):
            return None
        try:
            d = self.snapshot_dir(path)
            os.makedirs(d, exist_ok=True)
            last = self.snapshots(path)
            if last:
                with open(path, "rb") as a, open(last[0][0], "rb") as b:
                    if a.read() == b.read():
                        return None
            stamp = time.strftime("%Y-%m-%d %H-%M-%S", time.localtime(os.path.getmtime(path)))
            stem = os.path.splitext(os.path.basename(path))[0]
            dest = os.path.join(d, f"{stem} {stamp}.cueshow")
            k = 2
            while os.path.exists(dest):
                dest = os.path.join(d, f"{stem} {stamp} ({k}).cueshow")
                k += 1
            shutil.copy2(path, dest)
            for old, _t in self.snapshots(path)[SNAP_KEEP:]:
                os.remove(old)
            return dest
        except OSError as e:
            self.status(tr("Copia precedente non salvata: {0}", e))
            return None

    @staticmethod
    def _snapshot_drop_same(snap, path):
        import filecmp
        try:
            if snap and filecmp.cmp(snap, path, shallow=False):
                os.remove(snap)
        except OSError:
            pass

    def snapshots_dialog(self):
        """File › Copie precedenti dello show…"""
        from ..ui_batch import SnapshotsDialog
        if not self.show_data.path:
            QMessageBox.information(self, tr("Copie precedenti"),
                                    tr("Lo show non è ancora stato salvato: non ci sono copie precedenti."))
            return None
        d = SnapshotsDialog(self)
        d.show()
        return d

    def restore_snapshot(self, snap):
        """Riporta lo show alla copia scelta: resta da salvare (l'attuale diventa a sua volta una copia)."""
        from ..model import Show
        if not self._confirm_discard():
            return False
        try:
            rec = Show.load(snap)
        except Exception as e:
            QMessageBox.critical(self, tr("Errore"), tr("Impossibile aprire lo show:\n{0}", e))
            return False
        rec.path = self.show_data.path
        rec.dirty = True
        self._set_show(rec)
        self.status(tr("Show riportato alla copia del {0}: salvalo per conservarlo",
                       time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(os.path.getmtime(snap)))))
        return True
