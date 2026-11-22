"""Modifica dello show: selezione, inserimento, spostamento, duplicazione, ispettore (parte di MainWindow)."""
from ..i18n import tr
import os

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QMessageBox, )

from ..model import (
    TYPE_LABELS, Cue, link_target_ok, new_cue, type_for_file,
)

FILE_FILTER = "Show Cuevivo (*.cueshow);;JSON (*.json);;Tutti i file (*)"


class EditingMixin:
    def _current_row(self):
        rows = self._selected_rows()
        return rows[0] if rows else -1

    def _selected_rows(self):
        return sorted({i.row() for i in self.table.selectionModel().selectedRows()})

    def _current_cue(self):
        r = self._current_row()
        return self.show_data.cues[r] if 0 <= r < len(self.show_data.cues) else None

    def _select_row(self, r):
        if 0 <= r < len(self.show_data.cues):
            self._select_rows([r])
        else:
            self.table.clearSelection()
            self.inspector.set_cue(None)

    def _select_rows(self, rows):
        rows = list(rows)
        sm = self.table.selectionModel()
        sm.clearSelection()
        for r in rows:
            sm.select(self.model.index(r, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        if rows:
            sm.setCurrentIndex(self.model.index(rows[0], 1), QItemSelectionModel.NoUpdate)
            self.table.scrollTo(self.model.index(rows[0], 0))

    def _selection_changed(self, *a):
        cue = self._current_cue()
        self.inspector.set_cue(cue)
        if self._select_guard:
            return
        r = self._current_row()
        if r >= 0:
            self._select_guard = True
            self.ctrl.set_playhead(r)
            self._select_guard = False

    def _insert_cues(self, cues, row=None):
        grid = self.show_data.current.is_grid
        if row is None:
            r = self._current_row()
            row = r + 1 if (r >= 0 and not grid) else len(self.show_data.cues)
        from ..groups import membership_for_insert
        # nel GRID ogni nuova cue ha la sua casella (non entra nel gruppo vicino)
        g = "" if grid else membership_for_insert(self.show_data.cues, row)
        self.model.beginResetModel()
        for i, c in enumerate(cues):
            if c.type != "group" and not c.group:
                c.group = g
            self.show_data.cues.insert(row + i, c)
        self.model.endResetModel()
        self.show_data.dirty = True
        for c in cues:
            self._preload(c)
        self._structure_changed()
        # (un gruppo Stinger può aver aggiunto PRE/POST attorno: si seleziona la cue nuova)
        self._select_row(next((k for k, x in enumerate(self.show_data.cues) if x is cues[0]), row) if cues else row)

    def add_cue(self, ctype, row=None, group=None):
        """Nuova cue (dopo la selezione). row/group: posizione e gruppo imposti (GRID, gruppo aperto)."""
        if ctype in ("audio", "video", "image", "pdf"):
            from ..model import MEDIA_EXT
            pat = " ".join("*" + e for e in sorted(MEDIA_EXT[ctype]))
            start = self.qs.value("last_dir", os.path.expanduser("~"))
            paths, _ = QFileDialog.getOpenFileNames(self, tr("Scegli file {0}", TYPE_LABELS[ctype]), start,
                                                    tr("{0} ({1});;Tutti (*)", TYPE_LABELS[ctype], pat))
            if not paths:
                return
            self.qs.setValue("last_dir", os.path.dirname(paths[0]))
            cues = [self._cue_for_file(p, ctype) for p in paths]
        else:
            c = new_cue(ctype, number=self.show_data.next_number())
            cur = self._current_cue()
            if ctype == "link":
                # collegamento alla cue selezionata (se può esserlo); altrimenti si sceglie nell'ispettore
                c.link_target = cur.id if link_target_ok(cur) else ""
            if ctype in ("fade", "control", "preset") and cur is not None:
                c.target = cur.number or cur.id
                if ctype == "preset":
                    c.name = tr("Cambia preset {0}", cur.name).strip()
                    c.fade_duration = 3.0
                if ctype == "fade":
                    c.name = tr("Fade out {0}", cur.name).strip()
                    c.stop_when_done = True
            if ctype == "osc":
                c.name = tr("Messaggio OSC")
            if ctype == "wait":
                c.duration = 5.0
            cues = [c]
        if group is not None:
            for c in cues:
                c.group = group
        self._insert_cues(cues, row)
        if ctype == "video":
            self._scan_subtitles(cues)

    def _cue_for_file(self, path, ctype=None):
        ctype = ctype or type_for_file(path) or "audio"
        c = Cue(ctype, number=self.show_data.next_number(),
                name=os.path.splitext(os.path.basename(path))[0], file=path)
        # numerazione progressiva anche per inserimenti multipli
        self.show_data.cues.append(c)
        c.number = self.show_data.next_number()
        self.show_data.cues.remove(c)
        return c

    def _files_dropped(self, paths, row, group=None):
        cues = []
        subs = []                     # .srt / .vtt: agganciati al video con lo stesso nome (o alla cue scelta)
        for p in paths:
            if os.path.isdir(p):
                for f in sorted(os.listdir(p)):
                    fp = os.path.join(p, f)
                    if type_for_file(fp):
                        cues.append(fp)
                    elif fp.lower().endswith((".srt", ".vtt")):
                        subs.append(fp)
            elif type_for_file(p):
                cues.append(p)
            elif p.lower().endswith((".srt", ".vtt")):
                subs.append(p)
        if subs and not cues:
            self._subs_dropped(subs, [])
            return
        made = []
        for p in cues:
            c = Cue(type_for_file(p), name=os.path.splitext(os.path.basename(p))[0], file=p)
            made.append(c)
        n = self.show_data.next_number()
        try:
            base = int(n)
        except ValueError:
            base = len(self.show_data.cues) + 1
        for i, c in enumerate(made):
            c.number = str(base + i)
            if group is not None:
                c.group = group
        if made:
            self._insert_cues(made, row)
            self._scan_subtitles(made)
            if subs:
                self._subs_dropped(subs, made)
        else:
            self.status(tr("Nessun file multimediale riconosciuto"))

    def _subs_dropped(self, subs, made):
        """File di sottotitoli trascinati: ognuno va al video (o audio) appena inserito il cui nome è l'inizio
        del suo («film.mp4» ← «film.it.srt»); gli altri alla cue audio/video selezionata."""
        from .. import srt
        media = [c for c in made if c.type in ("audio", "video")]
        cur = self._current_cue()
        groups = {}
        for p in subs:
            stem = os.path.basename(p).lower()
            tg = next((c for c in sorted(media, key=lambda c: -len(c.file))
                       if stem.startswith(os.path.splitext(os.path.basename(c.file))[0].lower())), None)
            if tg is None:
                tg = media[0] if len(media) == 1 else (cur if cur is not None and cur.type in ("audio", "video") else None)
            if tg is None:
                self.status(tr("Sottotitoli «{0}»: seleziona prima la cue audio o video", os.path.basename(p)))
                continue
            try:
                groups.setdefault(tg.id, (tg, []))[1].append(srt.make_track(p))
            except OSError as e:
                self.status(f"✘ {p}: {e}")
        for tg, tracks in groups.values():
            self.attach_subtitles(tg, tracks)

    def _rows_moved(self, rows, dest):
        from ..groups import block_end, membership_for_insert
        cues = self.show_data.cues
        rows = sorted(set(rows))
        for r in list(rows):                      # un gruppo si porta dietro le sue cue
            if 0 <= r < len(cues) and cues[r].type == "group":
                rows += list(range(r + 1, block_end(cues, r)))
        rows = sorted(set(r for r in rows if 0 <= r < len(cues)))
        if any(cues[r].type == "group" for r in rows):
            # niente gruppi dentro i gruppi: se la destinazione cade dentro un gruppo, va dopo di esso
            g = membership_for_insert(cues, dest)
            if g:
                hi = next(k for k, x in enumerate(cues) if x.id == g)
                dest = block_end(cues, hi)
        else:
            g = membership_for_insert(cues, dest)
            gi = next((k for k, x in enumerate(cues) if x.id == g), -1)
            for r in rows:                        # trascinate dentro un gruppo ne diventano membri
                cues[r].group = g if gi not in rows else cues[r].group
        moving = [cues[i] for i in rows if 0 <= i < len(cues)]
        before = sum(1 for i in rows if i < dest)
        rest = [c for i, c in enumerate(cues) if i not in rows]
        dest = max(0, min(len(rest), dest - before))
        self.model.beginResetModel()
        self.show_data.cues[:] = rest[:dest] + moving + rest[dest:]
        self.model.endResetModel()
        self._structure_changed(select=range(dest, dest + len(moving)))

    def _rows_copied(self, rows, dest):
        """Ctrl + trascina nella lista: le copie delle righe vanno alla riga «dest» (un gruppo con le sue cue;
        rilasciate dentro un gruppo, le cue ne diventano membri, un gruppo va dopo di esso)."""
        from ..groups import block_end, membership_for_insert
        cues = self.show_data.cues
        rows = sorted(set(r for r in rows if 0 <= r < len(cues)))
        for r in list(rows):
            if cues[r].type == "group":
                rows += list(range(r + 1, block_end(cues, r)))
        rows = sorted(set(rows))
        if not rows:
            return
        dest = max(0, min(int(dest), len(cues)))
        src = [cues[r] for r in rows]
        clones = self._clone_block(src)
        ids = {c.id for c in clones}
        for k in clones:
            if k.type != "group" and k.group not in ids:
                k.group = ""                       # prende il gruppo della posizione di arrivo
        if any(k.type == "group" for k in clones):
            g = membership_for_insert(cues, dest)
            if g:                                  # niente gruppi dentro i gruppi
                hi = next(i for i, x in enumerate(cues) if x.id == g)
                dest = block_end(cues, hi)
        self._insert_cues(clones, dest)
        self._select_rows(range(dest, dest + len(clones)))
        self.status(tr("{0} cue duplicate", len(clones)))

    def move_selected(self, delta):
        rows = self._selected_rows()
        if not rows:
            return
        dest = rows[0] + delta if delta < 0 else rows[-1] + 2
        if dest < 0 or rows[-1] + delta >= len(self.show_data.cues):
            return
        self._rows_moved(rows, dest)

    def duplicate(self):
        rows = self._selected_rows()
        if not rows:
            return
        from ..groups import block_end
        cues = self.show_data.cues
        for r in list(rows):                      # un gruppo si duplica con le sue cue
            if cues[r].type == "group":
                rows += list(range(r + 1, block_end(cues, r)))
        rows = sorted(set(rows))
        clones, idmap = [], {}
        for r in rows:
            c = cues[r].clone()
            idmap[cues[r].id] = c.id
            c.number = ""
            clones.append(c)
        for c in clones:
            if c.group in idmap:
                c.group = idmap[c.group]
                if c.type == "groupexit":       # la copia della cue di uscita chiude la copia del gruppo
                    c.target = c.group
            if c.type == "text" and c.srt_target in idmap:   # sottotitoli copiati col loro video
                c.srt_target = idmap[c.srt_target]
        n = self.show_data.next_number()
        try:
            for i, c in enumerate(clones):
                c.number = str(int(n) + i)
        except ValueError:
            pass
        last = rows[-1]
        if cues[last].group and not any(c.type == "group" for c in clones):
            pass                                   # duplicato di cue di un gruppo: resta nel gruppo
        elif clones and clones[0].type == "group":
            last = block_end(cues, rows[0]) - 1
        self._insert_cues(clones, last + 1)

    def delete_cues(self):
        if self.table.state() == QAbstractItemView.EditingState:
            return
        rows = self._selected_rows()
        if not rows:
            return
        from ..groups import block_end
        cues = self.show_data.cues
        heads = [r for r in rows if cues[r].type == "group"]
        if heads:
            extra = sorted({k for r in heads for k in range(r + 1, block_end(cues, r))} - set(rows))
            if extra and QMessageBox.question(
                    self, tr("Elimina gruppo"), tr("Eliminare il gruppo insieme alle sue {0} cue?\n(«No» elimina solo il gruppo: le cue restano nella lista)", len(extra))) == QMessageBox.Yes:
                rows = sorted(set(rows) | set(extra))
        doomed = [cues[r] for r in rows]
        # originali con collegamenti (fuori da quelli che si cancellano già): cancellarli o farli puntare altrove
        gone = {c.id for c in doomed}
        links = [l for l in self.show_data.links_to(gone) if l.id not in gone]
        extra_links = []
        if links:
            ans = self.ask_links_on_delete([c for c in doomed if any(l.link_target == c.id for l in links)], links)
            if ans is None:
                return
            if ans[0] == "delete":
                extra_links = links
            else:
                for l in links:
                    l.set_target(ans[1])
            for h in self.show_data.all_cues():      # gruppi Stinger che usano le cue cancellate come PRE/POST
                if h.type == "group" and h.group_mode == "stinger":
                    for f in ("st_pre", "st_post"):
                        if getattr(h, f) in gone:
                            setattr(h, f, ans[1].id if ans[0] == "retarget" else "")
        for c in doomed + extra_links:
            self.ctrl.stop_cue(c.id, 0)
        self.model.beginResetModel()
        for r in reversed(rows):
            del cues[r]
        if extra_links:                            # collegamenti anche in altri PANEL
            drop = {id(l) for l in extra_links}
            for lst in self.show_data.lists:
                lst.cues[:] = [c for c in lst.cues if id(c) not in drop]
        self.model.endResetModel()
        self._structure_changed()
        self._select_row(min(rows[0], len(cues) - 1))

    def ask_links_on_delete(self, originals, links):
        """Si cancellano cue che hanno collegamenti: ("delete", None) cancella anche i collegamenti,
        ("retarget", cue) li fa puntare a un'altra cue, None annulla."""
        from PySide6.QtWidgets import QInputDialog
        names = ", ".join(c.label() for c in originals[:4]) + (" …" if len(originals) > 4 else "")
        mb = QMessageBox(self)
        mb.setIcon(QMessageBox.Warning)
        mb.setWindowTitle(tr("Cue con collegamenti"))
        mb.setText(tr("{0} ha {1} collegamenti nella scaletta. Cosa ne faccio?", names, len(links)))
        b_del = mb.addButton(tr("Elimina anche i collegamenti"), QMessageBox.DestructiveRole)
        b_re = mb.addButton(tr("Collegali a un'altra cue…"), QMessageBox.AcceptRole)
        mb.addButton(tr("Annulla"), QMessageBox.RejectRole)
        mb.exec()
        clicked = mb.clickedButton()
        if clicked is b_del:
            return ("delete", None)
        if clicked is not b_re:
            return None
        gone = {c.id for c in originals}
        cands = [c for c in self.show_data.all_cues() if link_target_ok(c) and c.id not in gone]
        if not cands:
            QMessageBox.information(self, tr("Cue con collegamenti"), tr("Non ci sono altre cue a cui collegarli."))
            return None
        labels = [f"{c.number or '·'} – {c.name or TYPE_LABELS.get(c.type, c.type)}" for c in cands]
        item, ok = QInputDialog.getItem(self, tr("Collegali a un'altra cue"), tr("Nuova cue originale:"), labels, 0, False)
        if not ok:
            return None
        return ("retarget", cands[labels.index(item)])

    def toggle_disabled(self):
        """Abilita / disabilita le cue selezionate (un gruppo vale per tutte le sue cue): se ce n'è almeno una
        abilitata le disabilita tutte, altrimenti le riabilita."""
        rows = self._selected_rows()
        cues = [self.show_data.cues[r] for r in rows if 0 <= r < len(self.show_data.cues)]
        if not cues:
            return
        on = not all(c.disabled for c in cues)
        for c in cues:
            c.disabled = on
        self.show_data.dirty = True
        self._normalize_stingers()                 # Stinger: PRE e POST seguono la loro cue
        self.status(tr("{0} cue disabilitate", len(cues)) if on else tr("{0} cue abilitate", len(cues)))
        self._refresh_disabled()
        self.inspector.refresh_fields()

    def create_link(self):
        """Crea un collegamento alla cue selezionata, subito dopo di essa."""
        cur = self._current_cue()
        if not link_target_ok(cur):
            self.status(tr("Collegamento: scegli una cue (non un gruppo né un altro collegamento)"))
            return
        self.add_cue("link")

    def renumber(self):
        sh = self.show_data
        prefix = "" if sh.view == 0 else f"P{sh.view}."     # i PANEL non si sovrappongono alla MAIN
        for i, c in enumerate(sh.cues, start=1):
            c.number = f"{prefix}{i}"
        self.show_data.dirty = True
        self.model.refresh()
        self.inspector.rebuild()

    def _visual_size(self, cue):
        """Dimensioni del sorgente di una cue visiva non in riproduzione."""
        if not cue.file:
            return None
        if cue.type in ("image", "pdf"):
            img = self.ctrl.image(cue.file)
            return (img.width(), img.height()) if img is not None and not img.isNull() else None
        info = self.loader.get_info(cue.file)
        if info and info.get("width"):
            return info["width"], info["height"]
        return None

    def _preview_edited(self):
        self.show_data.dirty = True
        self.inspector.refresh_fields()

    def _inspector_edited(self, file_changed):
        cue = self.inspector.cue
        if cue is not None and (cue.type == "group" or cue.group) and self._normalize_stingers():
            r = self._current_row()                   # Stinger: PRE/POST aggiunte, tolte o ricollegate
            self._structure_changed(select=[r] if r >= 0 else None)
            self.inspector.refresh_fields()
        if cue is not None and cue.type == "group":
            need = cue.group_mode == "rloop" and cue.group_advance == "go"
            has = any(c.type == "groupexit" and c.group == cue.id for c in self.show_data.cues)
            if need and not has:
                r = self._current_row()
                self._structure_changed(select=[r] if r >= 0 else None)
        if file_changed and cue is not None:
            self._preload(cue)
        if cue is not None and not file_changed:
            for inst in list(self.ctrl.instances.values()):     # la cue suona: curva e volume valgono subito
                if inst.cue is cue:
                    inst.live_edit()
        self.model.refresh()
        self._update_standby()

    # ------------------------------------------------------------------ sottotitoli SRT
    def _srt_cue_for(self, target):
        return next((c for c in self.show_data.all_cues() if c.type == "text" and c.text_mode == "srt"
                     and c.srt_target == target.id), None)

    def attach_subtitles(self, target, tracks):
        """Tracce SRT per una cue audio/video: vanno nella sua cue SRT (una traccia della stessa lingua viene
        sostituita) oppure in una cue Testo nuova dopo di essa (fuori dai gruppi), che parte con lei.
        Restituisce la cue SRT."""
        from .. import srt
        sc = self._srt_cue_for(target)
        if sc is not None:
            cur = [dict(t) for t in sc.srt_tracks or []]
            for t in tracks:
                lg = srt.norm_lang(t.get("lang"))
                k = next((j for j, o in enumerate(cur) if lg and srt.norm_lang(o.get("lang")) == lg), None)
                if k is None:
                    cur.append(t)
                else:
                    cur[k] = t
            sc.srt_tracks = cur
            self.show_data.dirty = True
            self.model.beginResetModel()
            self.model.endResetModel()
            if self.inspector.cue is sc:
                self.inspector.rebuild()
            return sc
        c = new_cue("text", number=self.show_data.next_number(),
                    name=tr("Sottotitoli {0}", target.name or target.number).strip(),
                    text_mode="srt", srt_target=target.id, srt_tracks=list(tracks), srt_auto=True,
                    trigger="trigger")
        lst, i = self.show_data.list_of(target.id)
        if lst is None:
            return None
        from ..groups import block_end
        pos = i + 1
        if target.group:
            hi = lst.index_of(target.group)
            if hi >= 0:
                pos = block_end(lst.cues, hi)
        if lst is self.show_data.current:
            self._insert_cues([c], None if lst.is_grid else pos)
            r = lst.index_of(target.id)
            if r >= 0 and not lst.is_grid:
                self._select_row(r)
        else:
            lst.cues.insert(pos, c)
            self._structure_changed()
        self.status(tr("Sottotitoli agganciati a «{0}»: {1}", target.label(),
                       ", ".join(srt.lang_label(t.get("lang")) for t in tracks)))
        return c

    def add_subtitles(self):
        """Menu: file .srt / .vtt per la cue audio/video selezionata."""
        from .. import srt
        cur = self._current_cue()
        if cur is None or cur.type not in ("audio", "video"):
            self.status(tr("Sottotitoli: scegli una cue audio o video"))
            return
        start = os.path.dirname(cur.file) if cur.file else self.qs.value("last_dir", os.path.expanduser("~"))
        paths, _ = QFileDialog.getOpenFileNames(self, tr("Sottotitoli per «{0}»", cur.label()), start,
                                                tr("Sottotitoli (*.srt *.vtt);;Tutti (*)"))
        if not paths:
            return
        tracks = []
        for p in paths:
            try:
                tracks.append(srt.make_track(p))
            except OSError as e:
                self.status(f"✘ {p}: {e}")
        if tracks:
            self.attach_subtitles(cur, tracks)

    def _ask_subtitles(self, cue, streams):
        """Finestra: tracce scelte e azione («cue», «file», «both»); None = ignora."""
        from ..ui_subs import SubsFoundDialog
        dlg = SubsFoundDialog(self, os.path.basename(cue.file), streams)
        if dlg.exec() != SubsFoundDialog.Accepted:
            return None
        ns, act = dlg.result_choice()
        return (ns, act) if ns else None

    def _extract_subtitles(self, path, ns):
        from ..ui_subs import extract_with_progress
        return extract_with_progress(self, path, ns)

    def _scan_subtitles(self, cues):
        """Video appena inseriti: se contengono sottotitoli si chiede se importarli in una cue SRT agganciata
        o esportarli in file .srt accanto al video."""
        from .. import srt
        from ..ui_subs import export_paths, write_srt
        for c in cues:
            if c.type != "video" or not c.file:
                continue
            streams = srt.probe_subs(c.file)
            if not streams:
                continue
            ans = self._ask_subtitles(c, streams)
            if not ans:
                continue
            ns, act = ans
            try:
                texts = self._extract_subtitles(c.file, ns)
            except RuntimeError as e:
                QMessageBox.warning(self, tr("Sottotitoli"), tr("Estrazione non riuscita: {0}", e))
                continue
            if not texts:
                continue
            by_n = {st["n"]: st for st in streams}
            got = [(by_n[n], texts[n]) for n in ns if n in texts]
            if act in ("file", "both"):
                try:
                    paths = export_paths(c.file, [st["lang"] for st, _t in got])
                    for p, (_st, t) in zip(paths, got):
                        write_srt(p, t)
                    self.status(tr("Sottotitoli esportati: {0}", ", ".join(os.path.basename(p) for p in paths)))
                except OSError as e:
                    QMessageBox.warning(self, tr("Sottotitoli"), tr("Impossibile scrivere i file .srt: {0}", e))
            if act in ("cue", "both"):
                name = os.path.basename(c.file)
                tracks = [{"lang": st["lang"], "srt": t,
                           "name": f"{name} #{st['n'] + 1}" + (f" «{st['title']}»" if st.get("title") else "")}
                          for st, t in got]
                self.attach_subtitles(c, tracks)

    def _model_edited(self):
        self.inspector.refresh_fields()
        self._update_standby()

    def _preload(self, cue):
        if cue.file and cue.is_media() and cue.type != "pdf":      # i PDF non passano da ffprobe
            self.loader.get_info(cue.file)
            if cue.type == "audio" or (cue.type == "video" and cue.video_audio != "system"):
                self.loader.preload_audio(cue.file)   # i file senza audio non occupano memoria

    def _open_cue_outputs(self):
        """Apre in anticipo le schede usate dalle cue (un'apertura durante lo show darebbe un ritardo)."""
        for c in self.show_data.all_cues():
            if c.type in ("audio", "video") and c.audio_device:
                self.audio.ensure_output(c.audio_device)
        if self.audio.preview.get("enabled"):
            self.audio.ensure_output(self.audio.preview.get("device") or None)
