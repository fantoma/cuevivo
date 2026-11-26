"""Testi lunghi (nomi di cue e di file) che non devono allargare la finestra: etichette con i puntini e menu a
tendina di larghezza contenuta (l'elenco aperto mostra comunque i nomi interi)."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QComboBox, QLabel, QSizePolicy

MAX_HINT = 420          # larghezza «desiderata» massima di un'etichetta (px): oltre, si tronca con «…»
COMBO_CHARS = 24        # caratteri visibili di un menu a tendina con voci lunghe


class ElidedLabel(QLabel):
    """Etichetta su una riga che, se il testo non entra, lo tronca con «…» (il testo intero è nel suggerimento)
    invece di allargare la finestra. text() restituisce sempre il testo intero."""

    def __init__(self, text="", parent=None, mode=Qt.ElideRight):
        super().__init__(parent)
        self._full = ""
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text):
        self._full = str(text or "")
        self._elide()
        self.updateGeometry()

    def text(self):
        return self._full

    def full_text(self):
        return self._full

    def _elide(self):
        one = " ".join(self._full.split("\n"))
        shown = self.fontMetrics().elidedText(one, self._mode, max(0, self.contentsRect().width()))
        QLabel.setText(self, shown)
        self.setToolTip(self._full if shown != one else "")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (e.Type.FontChange, e.Type.StyleChange):
            self._elide()

    def minimumSizeHint(self):
        return QSize(24, super().minimumSizeHint().height())

    def sizeHint(self):
        w = self.fontMetrics().horizontalAdvance(" ".join(self._full.split("\n"))) + 8
        return QSize(min(w, MAX_HINT), super().sizeHint().height())


def tame_combo(cb, chars=COMBO_CHARS):
    """Menu a tendina con voci lunghe (nomi di cue o di file): larghezza contenuta, voce scelta troncata, elenco
    aperto largo quanto serve (fino a quasi tutto lo schermo)."""
    if cb.property("_tamed"):
        return
    cb.setProperty("_tamed", True)
    cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    cb.setMinimumContentsLength(chars)
    if cb.minimumWidth() <= 0:
        cb.setMinimumWidth(80)          # il minimo già calcolato da Qt (largo quanto la voce più lunga) non vale più
    v = cb.view()
    fm = cb.fontMetrics()
    widest = max((fm.horizontalAdvance(cb.itemText(i)) for i in range(cb.count())), default=0) + 40
    scr = cb.screen()
    limit = int(scr.availableGeometry().width() * 0.9) if scr is not None else 1200
    v.setMinimumWidth(min(widest, limit))
    v.setTextElideMode(Qt.ElideMiddle)
    if not cb.toolTip():                      # la voce scelta per intero nel suggerimento
        cb.setToolTip(cb.currentText())
        cb.currentTextChanged.connect(cb.setToolTip)


def tame_combos(widget, limit=360):
    """Tutti i menu a tendina del widget che vorrebbero essere più larghi di «limit» px."""
    for cb in widget.findChildren(QComboBox):
        fm = cb.fontMetrics()
        widest = max((fm.horizontalAdvance(cb.itemText(i)) for i in range(cb.count())), default=0)
        if widest > limit - 40:          # misura sulle voci: la sizeHint prima della prima comparsa non è affidabile
            tame_combo(cb)
