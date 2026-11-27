"""Controllo della versione disponibile sul sito, all'avvio, in un thread che non blocca il programma.

Se la versione pubblicata è più recente di questa, accanto al menu «Aiuto» compare la scritta rossa
«Vedi la nuova versione», che apre la pagina del programma. Senza rete (o con una risposta strana) non succede
nulla. Si disattiva con la variabile d'ambiente CUEVIVO_NO_UPDATE_CHECK=1.

Con la richiesta il sito riceve, per le statistiche d'uso: versione installata, sistema operativo con la sua
versione, architettura del processore e un codice anonimo dell'installazione (casuale, creato una volta e salvato
nella cartella dei dati; nessun dato personale).
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


# ------------------------------------------------------------------ dati per le statistiche d'uso
def os_family():
    from .system import IS_LINUX, IS_MAC, IS_WIN
    import sys
    return "windows" if IS_WIN else "macos" if IS_MAC else "linux" if IS_LINUX else sys.platform


def os_version():
    """Sistema operativo e versione in chiaro: «Ubuntu 24.04», «Windows 11 (build 22631)», «macOS 14.5»."""
    import os
    import platform
    import sys
    from .system import IS_LINUX, IS_MAC, IS_WIN
    try:
        if IS_WIN:
            build = sys.getwindowsversion().build
            return f"Windows {'11' if build >= 22000 else '10'} (build {build})"
        if IS_MAC:
            return "macOS " + (platform.mac_ver()[0] or platform.release())
        if IS_LINUX:
            info = {}
            for path in ("/etc/os-release", "/usr/lib/os-release"):
                if os.path.exists(path):
                    with open(path, encoding="utf-8", errors="replace") as f:
                        for line in f:
                            k, _, v = line.strip().partition("=")
                            info[k] = v.strip().strip('"')
                    break
            return f"{info.get('NAME') or 'Linux'} {info.get('VERSION_ID') or ''}".strip()
    except Exception:
        pass
    return platform.system() or sys.platform


def arch():
    """Architettura del processore, con nomi uniformi: x86_64, arm64…"""
    import platform
    m = (platform.machine() or "").lower()
    return {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64"}.get(m, m)


def install_id():
    """Codice anonimo dell'installazione: casuale, creato una volta sola nella cartella dei dati."""
    import os
    import uuid
    from .system import data_dir
    path = os.path.join(data_dir(), ".install-id")
    try:
        with open(path, encoding="ascii") as f:
            v = f.read().strip()
        if len(v) >= 16:
            return v
    except OSError:
        pass
    v = uuid.uuid4().hex
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="ascii") as f:
            f.write(v)
    except OSError:
        pass
    return v


def request_url(url=VERSION_URL):
    """Indirizzo della richiesta con i dati delle statistiche (versione, sistema, architettura, codice anonimo)."""
    import urllib.parse
    from . import __version__
    q = urllib.parse.urlencode({"v": __version__, "os": os_family(), "osver": os_version(), "arch": arch(),
                                "id": install_id()})
    return url + ("&" if "?" in url else "?") + q


def user_agent():
    from . import __version__
    from .appinfo import APP_NAME
    return f"{APP_NAME}/{__version__} ({os_family().capitalize()}; {os_version()}; {arch()})"


def fetch(url=VERSION_URL, timeout=TIMEOUT):
    """Versione pubblicata (None se non si riesce a leggerla). Bloccante: va usata in un thread."""
    import ssl
    import urllib.request
    try:
        import certifi                       # i Python di python.org su macOS non hanno i certificati di sistema
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    try:
        req = urllib.request.Request(request_url(url), headers={"User-Agent": user_agent()})
    except Exception:
        return None
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
        try:
            from shiboken6 import isValid
        except ImportError:                  # pragma: no cover
            def isValid(_o):
                return True
        if not (isValid(lab) and isValid(self.window)):
            self.label = None                # finestra o barra dei menu già chiuse (posizionamento in ritardo)
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
