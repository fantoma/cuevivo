"""Controllo della versione disponibile sul sito, all'avvio, in un thread che non blocca il programma.

Se la versione pubblicata è più recente di questa, accanto al menu «Aiuto» compare la scritta rossa
«Vedi la nuova versione», che apre la pagina del programma. Senza rete (o con una risposta strana) non succede
nulla. Si disattiva con la variabile d'ambiente CUEVIVO_NO_UPDATE_CHECK=1.
"""
import json
import re
import threading

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel

from .i18n import tr

VERSION_URL = "https://www.fantoma.it/cuevivo/version.php"
PAGE_URL = "https://www.fantoma.it/cuevivo"
TIMEOUT = 8.0


def parse_version(text):
    """Numero di versione dalla risposta del sito: testo semplice («1.0.32») o JSON ({"version": "1.0.32"}).
    None se non c'è."""
    text = (text or "").strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            text = str(data.get("version") or data.get("latest") or "")
        elif isinstance(data, (str, int, float)):
            text = str(data)
    except ValueError:
        pass
    m = re.search(r"\d+(?:\.\d+)+", text)
    return m.group(0) if m else None


def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def is_newer(remote, local):
    r, l = vtuple(remote), vtuple(local)
    if not r:
        return False
    n = max(len(r), len(l))
    return r + (0,) * (n - len(r)) > l + (0,) * (n - len(l))


def fetch(url=VERSION_URL, timeout=TIMEOUT):
    """Versione pubblicata (None se non si riesce a leggerla)."""
    import ssl
    import urllib.request
    from . import __version__
    from .appinfo import APP_NAME
    try:
        import certifi                       # i Python di python.org su macOS non hanno i certificati di sistema
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return parse_version(r.read(4096).decode("utf-8", errors="replace"))
    except Exception:
        return None


class UpdateChecker(QObject):
    """Controlla in un thread; il risultato torna nel thread di Qt con un segnale."""
    found = Signal(str)          # versione più recente disponibile

    def __init__(self, window, current, url=VERSION_URL):
        super().__init__(window)
        self.window = window
        self.current = current
        self.url = url
        self.label = None
        self.found.connect(self._show)

    def start(self):
        threading.Thread(target=self._run, name="update-check", daemon=True).start()

    def _run(self):
        v = fetch(self.url)
        if v and is_newer(v, self.current):
            try:
                self.found.emit(v)
            except RuntimeError:             # finestra già chiusa
                pass

    def _show(self, version):
        mb = self.window.menuBar()
        self.version = version
        if mb.isNativeMenuBar():
            # barra dei menu del sistema (macOS): niente scritte colorate, una voce in più dopo «Aiuto»
            if getattr(self, "menu", None) is None:
                self.menu = mb.addMenu(tr("Vedi la nuova versione"))
                act = self.menu.addAction(tr("Apri la pagina della versione {0}", version))
                act.triggered.connect(self.open_page)
            return
        if self.label is None:
            lab = QLabel(mb)
            lab.setTextFormat(Qt.RichText)
            lab.setOpenExternalLinks(True)
            lab.setCursor(Qt.PointingHandCursor)
            self.label = lab
            mb.installEventFilter(self)
        self.label.setText(f'<a href="{PAGE_URL}" style="color:#ff4040; font-weight:bold; '
                           f'text-decoration:none;">{tr("Vedi la nuova versione")}</a>')
        self.label.setToolTip(tr("Disponibile la versione {0} (questa è la {1}): apre {2}",
                                 version, self.current, PAGE_URL))
        self.label.adjustSize()
        self.label.show()
        self._place()
        QTimer.singleShot(0, self._place)

    def open_page(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(PAGE_URL))

    def _place(self):
        """La scritta sta subito a destra della voce «Aiuto» della barra dei menu."""
        lab = self.label
        if lab is None:
            return
        mb = self.window.menuBar()
        help_menu = getattr(self.window, "help_menu", None)
        g = mb.actionGeometry(help_menu.menuAction()) if help_menu is not None else None
        x = (g.right() + 12) if (g is not None and g.width() > 0) else 8
        lab.move(x, max(0, (mb.height() - lab.height()) // 2))
        lab.raise_()

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Resize, QEvent.LayoutRequest, QEvent.Show, QEvent.FontChange):
            QTimer.singleShot(0, self._place)
        return False
