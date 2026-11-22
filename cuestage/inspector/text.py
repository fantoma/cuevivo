"""Scheda dell'ispettore per le cue di testo (sopratitoli, sottotitoli SRT) (parte di Inspector)."""
import os

from ..i18n import tr
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSpinBox,
    QVBoxLayout, QWidget,
)


class TextTabMixin:
    # ------------------------------------------------------------------ testo (sottotitoli)
    def _tab_text(self):
        from PySide6.QtGui import QColor, QFont, QPixmap, QPainter as _P
        from PySide6.QtWidgets import QColorDialog, QFontComboBox, QPlainTextEdit as _PTE
        from ..text_render import FIT_MODES, parse_srt, render_text, split_phrases
        cue = self.cue
        w = QWidget()
        outer = QHBoxLayout(w)
        left = QVBoxLayout()
        # --- contenuto
        top = QHBoxLayout()
        mc = QComboBox()
        mc.addItem(tr("Sequenza di frasi: una per GO (sottotitoli)"), "sequence")
        mc.addItem(tr("Testo libero: tutto insieme"), "free")
        mc.addItem(tr("Sottotitoli a tempo (SRT) agganciati a una cue audio/video"), "srt")
        mc.setCurrentIndex(max(0, mc.findData(cue.text_mode)))
        top.addWidget(QLabel(tr("Modalità")))
        top.addWidget(mc, 1)
        imp = QPushButton(tr("Importa .txt / .srt…"))
        top.addWidget(imp)
        left.addLayout(top)
        ed = _PTE(cue.text_content)
        ed.setPlaceholderText(tr("Scrivi qui il testo. In sequenza: ogni frase è separata da una riga vuota; "
                              "una frase può avere più righe. «_» da solo = schermo vuoto."))
        f0 = ed.font()
        f0.setPointSizeF(f0.pointSizeF() * 1.1)
        ed.setFont(f0)
        left.addWidget(ed, 1)
        is_srt = cue.text_mode == "srt"
        srt_refresh = None
        if is_srt:
            ed.hide()
            imp.hide()
            sp_w, srt_refresh = self._srt_panel(cue)
            left.addWidget(sp_w, 1)
        rec_info = None
        if cue.text_mode == "sequence":
            rec_info = self._rec_row(cue, left)
        info = QLabel()
        info.setStyleSheet("color:#999;")
        info.setWordWrap(True)
        outer.addLayout(left, 3)

        # --- stile
        right = QVBoxLayout()
        f = QFormLayout()
        pre = QComboBox()
        presets = {"Sottotitolo in basso": ([5, 78, 90, 18], "center", "bottom"),
                   "Sopratitolo in alto": ([5, 3, 90, 18], "center", "top"),
                   "Centro dello schermo": ([10, 30, 80, 40], "center", "middle"),
                   "Schermo intero": ([3, 3, 94, 94], "center", "middle")}
        pre.addItem(tr("— posizione rapida —"))
        for k in presets:
            pre.addItem(tr(k), k)
        f.addRow(tr("Area"), pre)
        arow = QHBoxLayout()
        spins = []
        for j, lab in enumerate(("x", "y", tr("larg."), tr("alt."))):
            sp = QDoubleSpinBox()
            sp.setRange(0, 100)
            sp.setDecimals(1)
            sp.setSuffix(" %")
            sp.setValue(float((cue.text_area or [5, 78, 90, 18])[j]))
            sp.setToolTip(tr("{0} dell'area in % dell'uscita", lab))
            spins.append(sp)
            arow.addWidget(QLabel(lab))
            arow.addWidget(sp)
        f.addRow("", arow)
        al = QHBoxLayout()
        ha = self._combo("text_halign", ["left", "center", "right"], {"left": tr("sinistra"), "center": tr("centro"), "right": tr("destra")})
        va = self._combo("text_valign", ["top", "middle", "bottom"], {"top": tr("in alto"), "middle": tr("al centro"), "bottom": tr("in basso")})
        al.addWidget(ha)
        al.addWidget(va)
        f.addRow(tr("Allineamento"), al)
        fr = QHBoxLayout()
        fc = QFontComboBox()
        fc.setCurrentFont(QFont(cue.text_font or "Sans Serif"))
        fr.addWidget(fc, 1)
        sz = self._dspin("text_size", 6, 400, 1, 0, suffix=" px")
        sz.setToolTip(tr("Dimensione riferita a un'uscita alta 1080 px"))
        fr.addWidget(sz)
        f.addRow(tr("Carattere"), fr)
        st = QHBoxLayout()
        for attr, lab in (("text_bold", tr("Grassetto")), ("text_italic", tr("Corsivo"))):
            cb = QCheckBox(lab)
            cb.setChecked(bool(getattr(cue, attr)))
            cb.toggled.connect(lambda on, attr=attr: (setattr(cue, attr, on), self._emit()))
            st.addWidget(cb)

        def color_btn(attr, allow_none=False):
            b = QPushButton()
            b.setFixedWidth(70)

            def paint():
                c = getattr(cue, attr)
                b.setText("nessuno" if not c else "")
                b.setStyleSheet(f"background:{c};" if c else "")
            paint()

            def pick():
                c = QColorDialog.getColor(QColor(getattr(cue, attr) or "#000000"), self, tr("Colore"))
                if c.isValid():
                    setattr(cue, attr, c.name())
                    paint()
                    self._emit()
            b.clicked.connect(pick)
            if allow_none:
                b.setContextMenuPolicy(Qt.CustomContextMenu)
                b.setToolTip(tr("Clic: scegli · tasto destro: nessuno sfondo"))
                b.customContextMenuRequested.connect(lambda *_: (setattr(cue, attr, ""), paint(), self._emit()))
            return b
        st.addWidget(QLabel(tr("Colore")))
        st.addWidget(color_btn("text_color"))
        st.addStretch(1)
        f.addRow(tr("Stile"), st)
        ol = QHBoxLayout()
        ol.addWidget(self._dspin("text_outline", 0, 30, 0.5, 1, suffix=" px"))
        ol.addWidget(color_btn("text_outline_color"))
        f.addRow(tr("Contorno"), ol)
        bgr = QHBoxLayout()
        bgr.addWidget(color_btn("text_bg", allow_none=True))
        op = self._dspin("text_bg_opacity", 0, 100, 5, 0, suffix=" %")
        bgr.addWidget(op)
        bgr.addWidget(self._combo("text_bg_mode", ["block", "area"], {"block": tr("dietro il testo"), "area": tr("tutta l'area")}))
        f.addRow(tr("Sfondo"), bgr)
        f.addRow(tr("Margine interno"), self._dspin("text_padding", 0, 200, 1, 0, suffix=" px"))
        f.addRow(tr("Adattamento"), self._combo("text_fit", list(FIT_MODES), FIT_MODES))
        ml = QSpinBox()
        ml.setRange(0, 20)
        ml.setSpecialValueText(tr("senza limite"))
        ml.setValue(int(cue.text_max_lines or 0))
        ml.valueChanged.connect(lambda v: (setattr(cue, "text_max_lines", v), self._emit()))
        f.addRow(tr("Righe massime"), ml)
        f.addRow(tr("Interlinea"), self._dspin("text_spacing", 60, 250, 5, 0, suffix=" %"))
        f.addRow(tr("Dissolvenza tra frasi"), self._dspin("text_fade", 0, 10, 0.1, 2))
        if cue.text_mode == "free":
            dur = self._dspin("duration", 0, 36000, 0.5, 1)
            dur.setSpecialValueText(tr("finché non si ferma"))
            f.addRow(tr("Durata"), dur)
        f.addRow(tr("Layer"), self._ispin("layer", 0, 99))
        if cue.text_mode in ("sequence", "srt"):
            nm = QCheckBox(tr("Non inviare allo schermo master"))
            nm.setChecked(bool(cue.text_no_master))
            nm.setToolTip(tr("Il testo non compare sullo schermo di uscita di questa istanza (né di uno slave di "
                             "ridondanza, che fa come il master) ma solo nella finestra di anteprima; uno slave "
                             "collegato non di ridondanza lo mostra sul suo schermo"))
            nm.toggled.connect(lambda on: (setattr(cue, "text_no_master", on), self._emit()))
            f.addRow("", nm)
        right.addLayout(f)
        # --- anteprima
        prow = QHBoxLayout()
        prow.addWidget(QLabel(tr("Anteprima sottotitolo") if cue.text_mode == "srt" else tr("Anteprima frase")))
        pn = QSpinBox()
        pn.setRange(1, 1)
        prow.addWidget(pn)
        live = QPushButton(tr("Mostra in uscita da questa frase"))
        prow.addWidget(live)
        prow.addStretch(1)
        prev = QLabel()
        prev.setFixedSize(320, 180)
        prev.setStyleSheet("background:#111;border:1px solid #444;")
        pv = QHBoxLayout()
        pv.addWidget(prev)
        pvr = QVBoxLayout()
        pvr.addLayout(prow)
        pvr.addWidget(info)
        pvr.addStretch(1)
        pv.addLayout(pvr, 1)
        left.addLayout(pv)
        sa_r = QScrollArea()
        sa_r.setWidgetResizable(True)
        sa_r.setFrameShape(QFrame.NoFrame)
        rw = QWidget()
        rw.setLayout(right)
        sa_r.setWidget(rw)
        outer.addWidget(sa_r, 2)

        def phrases():
            if cue.text_mode == "srt":
                from ..srt import parse, pick_track
                tk = pick_track(cue, self.show_fn())
                return [e[2] for e in parse(tk.get("srt") or "").entries] if tk else []
            return split_phrases(cue.text_content) if cue.text_mode == "sequence" else [cue.text_content or ""]

        def redraw():
            ps = phrases() or [""]
            pn.blockSignals(True)
            pn.setRange(1, max(1, len(ps)))
            pn.blockSignals(False)
            if cue.text_mode == "srt":
                info.setText(tr("{0} sottotitoli · compaiono seguendo la posizione del file della cue agganciata "
                                "(punto IN, loop, pausa e salti compresi); finita quella, finiscono anche loro",
                                len(phrases())))
            else:
                info.setText(tr("{0} frasi · GO avanza di una frase, dopo l'ultima il GO esce · Alt+→ / Alt+← frase successiva / precedente · ESC esce", len(ps))
                             if cue.text_mode == "sequence" else tr("Il testo compare intero all'avvio della cue"))
            if srt_refresh is not None:
                srt_refresh()
            if rec_info is not None:
                n = sum(1 for x in (cue.text_times or [])[:len(ps)]
                        if isinstance(x, (list, tuple)) and x and x[0] is not None)
                rec_info.setText(tr("tempi: {0}/{1} frasi", n, len(ps)))
            W, H = self.ctrl.comp.out_size
            img = render_text(cue, ps[pn.value() - 1], int(W), int(H))
            pm = QPixmap(320, 180)
            pm.fill(QColor("#111"))
            pp = _P(pm)
            pp.setRenderHint(_P.SmoothPixmapTransform, True)
            pp.drawImage(pm.rect(), img)
            x, y, ww, hh = (float(v) for v in cue.text_area)
            pp.setPen(QColor(80, 160, 255))
            pp.drawRect(int(320 * x / 100), int(180 * y / 100), int(320 * ww / 100), int(180 * hh / 100))
            pp.end()
            prev.setPixmap(pm)
            inst = self.ctrl.instances.get(cue.id)
            if inst is not None and hasattr(inst, "refresh"):
                inst.refresh()
        self._text_redraw = redraw

        def text_changed():
            cue.text_content = ed.toPlainText()
            self.show_fn().dirty = True
            redraw()
        ed.textChanged.connect(text_changed)
        mc.currentIndexChanged.connect(lambda j: (setattr(cue, "text_mode", mc.itemData(j)), self._emit(),
                                                  QTimer.singleShot(0, self.rebuild)))
        fc.currentFontChanged.connect(lambda font: (setattr(cue, "text_font", font.family()), self._emit()))
        pn.valueChanged.connect(lambda _v: redraw())
        self._srt_preview_n = pn.value

        def area_changed(*_):
            cue.text_area = [round(sp.value(), 1) for sp in spins]
            self._emit()
        for sp in spins:
            sp.valueChanged.connect(area_changed)

        def preset(j):
            if j <= 0:
                return
            area, h, v = presets[pre.itemData(j)]
            cue.text_area = list(area)
            cue.text_halign, cue.text_valign = h, v
            pre.setCurrentIndex(0)
            self._emit()
            QTimer.singleShot(0, self.rebuild)
        pre.currentIndexChanged.connect(preset)

        def do_import():
            path, _ = QFileDialog.getOpenFileName(self, tr("Importa testo"), "", tr("Testo (*.txt *.srt);;Tutti (*)"))
            if not path:
                return
            try:
                raw = open(path, encoding="utf-8-sig", errors="replace").read()
            except OSError as err:
                info.setText(f"✘ {err}")
                return
            ps = parse_srt(raw) if path.lower().endswith(".srt") else split_phrases(raw)
            ed.setPlainText("\n\n".join(ps))
        imp.clicked.connect(do_import)

        def show_live():
            inst = self.ctrl.instances.get(cue.id)
            if inst is None or not hasattr(inst, "goto"):
                self.ctrl.start_cue(cue, cascade=False)
                inst = self.ctrl.instances.get(cue.id)
            if inst is not None and hasattr(inst, "goto"):
                inst.goto(pn.value() - 1)
        live.clicked.connect(show_live)
        live.setVisible(not is_srt)
        redraw()
        return w

    def _rec_row(self, cue, layout):
        """Sequenza di frasi: memorizza i tempi a ogni GO (sul file di una cue audio/video agganciata),
        poi «Tempi e SRT…» per correggerli, esportarli o trasformare la cue in sottotitoli a tempo."""
        from ..model import TYPE_LABELS
        sh = self.show_fn()
        row = QHBoxLayout()
        cb = QCheckBox(tr("Memorizza i tempi a ogni GO"))
        cb.setChecked(bool(cue.text_rec))
        cb.setToolTip(tr("Mentre la cue va (prova o spettacolo) ogni frase registra quando compare e quando "
                         "sparisce; i tempi vecchi di quella frase vengono sostituiti"))
        cb.toggled.connect(lambda on: (setattr(cue, "text_rec", on), self._emit()))
        row.addWidget(cb)
        row.addWidget(QLabel(tr("sul file di")))
        ref = QComboBox()
        ref.addItem(tr("— nessuna: dall'avvio della cue —"), "")
        for lst in sh.lists:
            for c in lst.cues:
                if c.type in ("audio", "video"):
                    ref.addItem(f"{lst.name} · {c.number or '·'} – {c.name or TYPE_LABELS.get(c.type, c.type)}", c.id)
        j = ref.findData(cue.srt_target)
        if j < 0 and cue.srt_target:
            ref.addItem("⚠ " + tr("cue agganciata eliminata"), cue.srt_target)
            j = ref.count() - 1
        ref.setCurrentIndex(max(0, j))
        ref.setToolTip(tr("Cue audio/video a cui agganciare i tempi: deve essere già partita quando parte "
                          "questa cue (per esempio subito prima, con questa «con la precedente»)"))
        ref.currentIndexChanged.connect(lambda k: (setattr(cue, "srt_target", ref.itemData(k) or ""), self._emit()))
        row.addWidget(ref, 1)
        info = QLabel()
        info.setStyleSheet("color:#999;")
        row.addWidget(info)
        btn = QPushButton(tr("Tempi e SRT…"))

        def edit():
            from ..ui_subs import TimesDialog
            dlg = TimesDialog(self, cue, sh)
            if dlg.exec() or dlg.markers_added:
                self._emit()
                if dlg.converted:
                    QTimer.singleShot(0, self.rebuild)
        btn.clicked.connect(edit)
        row.addWidget(btn)
        layout.addLayout(row)
        return info

    # ------------------------------------------------------------------ sottotitoli a tempo (SRT)
    def _srt_panel(self, cue):
        """Cue agganciata, tracce (una per lingua), lingua, ritardo e controllo dei tempi.
        Restituisce (widget, aggiorna)."""
        from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QMessageBox, QTableWidget, QTableWidgetItem
        from .. import srt
        from ..model import TYPE_LABELS
        from ..ui_subs import SubsFoundDialog, export_paths, extract_with_progress, write_srt
        sh = self.show_fn()
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        f = QFormLayout()
        # --- cue agganciata
        trow = QHBoxLayout()
        tcb = QComboBox()
        tcb.addItem(tr("— scegli la cue audio/video —"), "")
        for lst in sh.lists:
            for c in lst.cues:
                if c.type in ("audio", "video"):
                    tcb.addItem(f"{lst.name} · {c.number or '·'} – {c.name or TYPE_LABELS.get(c.type, c.type)}", c.id)
        i = tcb.findData(cue.srt_target)
        if i < 0 and cue.srt_target:
            tcb.addItem("⚠ " + tr("cue agganciata eliminata"), cue.srt_target)
            i = tcb.count() - 1
        tcb.setCurrentIndex(max(0, i))
        trow.addWidget(tcb, 1)
        go = QPushButton(tr("Vai"))
        go.clicked.connect(lambda: self.reveal_fn(cue.srt_target)
                           if (cue.srt_target and getattr(self, "reveal_fn", None)) else None)
        trow.addWidget(go)
        f.addRow(tr("Cue agganciata"), trow)
        auto = QCheckBox(tr("Parte da sola quando parte la cue agganciata"))
        auto.setChecked(bool(cue.srt_auto))
        auto.toggled.connect(lambda on: (setattr(cue, "srt_auto", on), self._emit()))
        f.addRow("", auto)
        # --- lingua
        lrow = QHBoxLayout()
        lcb = QComboBox()
        lrow.addWidget(lcb, 1)
        lrow.addWidget(QLabel(tr("Lingua dello show")))
        scb = QComboBox()
        scb.setEditable(True)
        scb.setToolTip(tr("Lingua usata da tutte le cue SRT impostate su «lingua dello show» "
                          "(si cambia anche durante lo spettacolo; OSC /text/lang <codice>)"))
        lrow.addWidget(scb, 1)
        f.addRow(tr("Lingua"), lrow)
        f.addRow(tr("Ritardo"), self._dspin("srt_offset", -3600, 3600, 0.1, 2))
        v.addLayout(f)
        # --- tracce
        tbl = QTableWidget(0, 4)
        tbl.setHorizontalHeaderLabels([tr("Lingua"), tr("File"), tr("Sottotitoli"), tr("Tempi")])
        tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        tbl.verticalHeader().hide()
        hh = tbl.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        for k in (0, 2, 3):
            hh.setSectionResizeMode(k, QHeaderView.ResizeToContents)
        tbl.setToolTip(tr("Doppio clic sulla lingua per cambiarne il codice (it, en, sl…)"))
        tbl.setMinimumHeight(70)
        tbl.setMaximumHeight(130)
        v.addWidget(tbl)
        brow = QHBoxLayout()
        b_add = QPushButton(tr("Aggiungi .srt…"))
        b_vid = QPushButton(tr("Dal video…"))
        b_vid.setToolTip(tr("Importa le tracce di sottotitoli contenute nel file della cue agganciata"))
        b_exp = QPushButton(tr("Esporta .srt…"))
        b_del = QPushButton(tr("Rimuovi"))
        b_mk = QPushButton(tr("Marker…"))
        b_mk.setToolTip(tr("Marker sulla cue agganciata all'inizio dei sottotitoli (lingua in uso)"))
        for b in (b_add, b_vid, b_exp, b_del, b_mk):
            brow.addWidget(b)
        brow.addStretch(1)
        v.addLayout(brow)
        chk = QLabel()
        chk.setWordWrap(True)
        chk.setTextFormat(Qt.RichText)
        chk.setTextInteractionFlags(Qt.TextSelectableByMouse)
        chk.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        v.addWidget(chk, 1)
        busy = [False]

        def tracks():
            return [t for t in (cue.srt_tracks or []) if isinstance(t, dict)]

        def fill_langs():
            busy[0] = True
            lcb.clear()
            sl = srt.show_lang(sh)
            loc = srt.local_lang()
            lcb.addItem(tr("Lingua di questa istanza ({0})", srt.lang_label(loc)) if loc else
                        tr("Lingua dello show ({0})", srt.lang_label(sl) if sl else tr("prima traccia")), "")
            seen = []
            for t in tracks():
                lg = srt.norm_lang(t.get("lang"))
                if lg and lg not in seen:
                    seen.append(lg)
                    lcb.addItem(srt.lang_label(lg), lg)
            j = lcb.findData(srt.norm_lang(cue.srt_lang))
            if j < 0 and cue.srt_lang:
                lcb.addItem("⚠ " + srt.lang_label(cue.srt_lang), cue.srt_lang)
                j = lcb.count() - 1
            lcb.setCurrentIndex(max(0, j))
            scb.clear()
            scb.addItem(tr("— prima traccia —"), "")
            for lg in srt.show_languages(sh):
                scb.addItem(srt.lang_label(lg), lg)
            j = scb.findData(sl)
            if j < 0 and sl:
                scb.addItem(srt.lang_label(sl), sl)
                j = scb.count() - 1
            scb.setCurrentIndex(max(0, j))
            busy[0] = False

        def refresh():
            busy[0] = True
            sel = tbl.currentRow()
            tl = tracks()
            tbl.setRowCount(len(tl))
            active = srt.pick_track(cue, sh)
            lines = []
            for r, t in enumerate(tl):
                p = srt.parse(t.get("srt") or "")
                iss = srt.all_issues(sh, cue, t, self.loader)
                bad = sum(1 for x in iss if x[0] == "error")
                cells = [srt.norm_lang(t.get("lang")) or "?", t.get("name") or "",
                         str(len(p.entries)), "✘" if bad else ("⚠" if iss else "✔")]
                for col, txt in enumerate(cells):
                    it = QTableWidgetItem(txt)
                    if col != 0:
                        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    if t is active:
                        fnt = it.font()
                        fnt.setBold(True)
                        it.setFont(fnt)
                    tbl.setItem(r, col, it)
                span = (f"{srt.fmt_time(p.entries[0][0])[:8]} → {srt.fmt_time(p.last_end())[:8]}"
                        if p.entries else "")
                head = f"<b>{srt.lang_label(t.get('lang'))}</b> · {tr('{0} sottotitoli', len(p.entries))}" + \
                    (f" · {span}" if span else "")
                body = "<br>".join(srt.issue_text(x) for x in iss) or "✔ " + tr("tempi conformi")
                lines.append(head + "<br>" + body)
            if 0 <= sel < len(tl):
                tbl.selectRow(sel)
            tg, dur, a, b = srt.target_info(sh, cue, self.loader)
            if not tl:
                lines.insert(0, tr("Nessun file di sottotitoli: aggiungi un .srt (uno per lingua)"))
            if tg is None:
                lines.insert(0, "⚠ " + tr("Scegli la cue audio/video a cui agganciare i sottotitoli"))
            elif dur <= 0:
                lines.insert(0, tr("Durata del file di «{0}» non ancora nota: il controllo dei tempi sul file "
                                   "arriva appena è letta", tg.label()))
            chk.setText("<br><br>".join(lines))
            b_vid.setEnabled(tg is not None and tg.type == "video" and bool(tg.file))
            b_exp.setEnabled(bool(tl))
            b_del.setEnabled(bool(tl))
            b_mk.setEnabled(bool(tl) and tg is not None)
            busy[0] = False

        def changed(rebuild_langs=True):
            self._emit()
            if rebuild_langs:
                fill_langs()

        def target_changed(j):
            cue.srt_target = tcb.itemData(j) or ""
            changed(False)
        tcb.currentIndexChanged.connect(target_changed)

        def lang_cell(it):
            if busy[0] or it.column() != 0:
                return
            tl = tracks()
            if 0 <= it.row() < len(tl):
                tl[it.row()]["lang"] = srt.norm_lang(it.text())
                cue.srt_tracks = tl
                QTimer.singleShot(0, changed)
        tbl.itemChanged.connect(lang_cell)

        def cue_lang(j):
            if not busy[0]:
                cue.srt_lang = lcb.itemData(j) or ""
                changed(False)
        lcb.currentIndexChanged.connect(cue_lang)

        def show_lang_set(*_):
            if busy[0]:
                return
            j = scb.currentIndex()
            data = scb.itemData(j) if j >= 0 and scb.itemText(j) == scb.currentText() else None
            code = data if data is not None else srt.norm_lang(scb.currentText())
            sh.settings["sub_lang"] = code or ""
            sh.dirty = True
            QTimer.singleShot(0, changed)
        scb.activated.connect(show_lang_set)
        scb.lineEdit().editingFinished.connect(show_lang_set)

        def add_files():
            tg = sh.by_id(cue.srt_target) if cue.srt_target else None
            start = os.path.dirname(tg.file) if (tg is not None and getattr(tg, "file", "")) else ""
            paths, _ = QFileDialog.getOpenFileNames(self, tr("Sottotitoli"), start,
                                                    tr("Sottotitoli (*.srt *.vtt);;Tutti (*)"))
            add_tracks([srt.make_track(p) for p in paths if os.path.isfile(p)])

        def add_tracks(new):
            tl = [dict(t) for t in tracks()]
            for t in new:
                lg = srt.norm_lang(t.get("lang"))
                k = next((j for j, o in enumerate(tl) if lg and srt.norm_lang(o.get("lang")) == lg), None)
                if k is None:
                    tl.append(t)
                else:
                    tl[k] = t
            cue.srt_tracks = tl
            changed()
        self._srt_add_tracks = add_tracks

        def from_video():
            tg = sh.by_id(cue.srt_target) if cue.srt_target else None
            if tg is None or not tg.file:
                return
            streams = srt.probe_subs(tg.file)
            if not any(s_.get("text") for s_ in streams):
                QMessageBox.information(self, tr("Sottotitoli"),
                                        tr("Il file di «{0}» non contiene sottotitoli in formato testo", tg.label()))
                return
            dlg = SubsFoundDialog(self, os.path.basename(tg.file), streams, ask_action=False)
            if dlg.exec() != SubsFoundDialog.Accepted:
                return
            ns, _act = dlg.result_choice()
            try:
                texts = extract_with_progress(self, tg.file, ns) or {}
            except RuntimeError as e:
                QMessageBox.warning(self, tr("Sottotitoli"), tr("Estrazione non riuscita: {0}", e))
                return
            by_n = {s_["n"]: s_ for s_ in streams}
            name = os.path.basename(tg.file)
            add_tracks([{"lang": by_n[n]["lang"], "srt": texts[n],
                         "name": f"{name} #{n + 1}" + (f" «{by_n[n]['title']}»" if by_n[n].get("title") else "")}
                        for n in ns if n in texts])

        def export():
            tl = tracks()
            r = tbl.currentRow()
            if not (0 <= r < len(tl)):
                r = 0
            t = tl[r]
            tg = sh.by_id(cue.srt_target) if cue.srt_target else None
            base = tg.file if (tg is not None and getattr(tg, "file", "")) else os.path.join(
                os.path.expanduser("~"), cue.name or "sottotitoli")
            sug = export_paths(base, [srt.norm_lang(t.get("lang"))])[0]
            path, _ = QFileDialog.getSaveFileName(self, tr("Esporta sottotitoli"), sug, tr("Sottotitoli (*.srt)"))
            if path:
                try:
                    write_srt(path, t.get("srt") or "")
                except OSError as e:
                    QMessageBox.warning(self, tr("Sottotitoli"), str(e))

        def remove():
            tl = tracks()
            r = tbl.currentRow()
            if 0 <= r < len(tl):
                del tl[r]
                cue.srt_tracks = tl
                changed()
        def markers(which):
            tg = sh.by_id(cue.srt_target) if cue.srt_target else None
            tk = srt.pick_track(cue, sh)
            if tg is None or tk is None:
                return
            es = srt.parse(tk.get("srt") or "").entries
            if which == "one":
                k = int(getattr(self, "_srt_preview_n", lambda: 1)()) - 1
                es = es[k:k + 1] if 0 <= k < len(es) else []
            off = float(cue.srt_offset or 0)
            n = srt.add_markers(tg, [(e[0] + off, e[2]) for e in es])
            self._emit()
            chk.setText(tr("{0} marker aggiunti", n) + "<br><br>" + chk.text())

        from PySide6.QtWidgets import QMenu
        mk_menu = QMenu(b_mk)
        mk_menu.addAction(tr("Per tutti i sottotitoli"), lambda: markers("all"))
        mk_menu.addAction(tr("Per il sottotitolo in anteprima"), lambda: markers("one"))
        b_mk.setMenu(mk_menu)
        b_add.clicked.connect(add_files)
        b_vid.clicked.connect(from_video)
        b_exp.clicked.connect(export)
        b_del.clicked.connect(remove)
        fill_langs()
        refresh()
        outer = QScrollArea()
        outer.setWidgetResizable(True)
        outer.setFrameShape(QFrame.NoFrame)
        outer.setWidget(w)
        return outer, refresh
