"""Testi lunghi (nomi di cue e di file) che non devono allargare la finestra: etichette con i puntini e menu a
tendina di larghezza contenuta (l'elenco aperto mostra comunque i nomi interi)."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QComboBox, QLabel, QSizePolicy

MAX_HINT = 420          # larghezza «desiderata» massima di un'etichetta (px): oltre, si tronca con «…»
COMBO_CHARS = 32        # caratteri massimi visibili nella voce scelta di un menu a tendina (oltre: troncata)


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


def fit_combo(cb, chars=COMBO_CHARS):
    """Menu a tendina largo quanto la voce scelta (cambia con lei), al massimo «chars» caratteri (oltre, la voce
    si tronca); l'elenco aperto è largo quanto la voce più lunga (fino a quasi tutto lo schermo)."""
    from PySide6.QtWidgets import QStyle, QStyleOptionComboBox
    if not cb.property("_fit"):
        cb.setProperty("_fit", True)
        sp = cb.sizePolicy()
        sp.setHorizontalPolicy(QSizePolicy.Fixed)
        cb.setSizePolicy(sp)
        cb.currentIndexChanged.connect(lambda *_: fit_combo(cb, chars))
        if cb.isEditable():
            cb.editTextChanged.connect(lambda *_: fit_combo(cb, chars))
        m = cb.model()
        for sig in (m.rowsInserted, m.rowsRemoved, m.modelReset):
            sig.connect(lambda *_: fit_combo(cb, chars))
        if not cb.toolTip():                  # la voce scelta per intero nel suggerimento
            cb.setProperty("_auto_tip", True)
    fm = cb.fontMetrics()
    text = cb.currentText()
    tw = min(fm.horizontalAdvance(text or "  "), fm.averageCharWidth() * chars)
    opt = QStyleOptionComboBox()
    cb.initStyleOption(opt)
    if cb.currentIndex() >= 0 and not cb.itemIcon(cb.currentIndex()).isNull():
        tw += cb.iconSize().width() + 4
    sz = cb.style().sizeFromContents(QStyle.CT_ComboBox, opt, QSize(tw, fm.height()), cb)
    w = max(56, sz.width() + (8 if cb.isEditable() else 2))
    if cb.width() != w or cb.minimumWidth() != w:
        cb.setFixedWidth(w)
    widest = max((fm.horizontalAdvance(cb.itemText(i)) for i in range(cb.count())), default=0) + 40
    scr = cb.screen()
    limit = int(scr.availableGeometry().width() * 0.9) if scr is not None else 1200
    cb.view().setMinimumWidth(min(widest, limit))
    cb.view().setTextElideMode(Qt.ElideMiddle)
    if cb.property("_auto_tip"):
        cb.setToolTip(text if fm.horizontalAdvance(text) > tw else "")


def _pack_left(layout):
    """Riga orizzontale senza nessun elemento che si allarghi: si aggiunge uno spazio in fondo, così i campi
    restano raggruppati a sinistra invece di distribuirsi su tutta la riga."""
    from PySide6.QtWidgets import QHBoxLayout
    if not isinstance(layout, QHBoxLayout) or layout.property("_packed"):
        return
    for i in range(layout.count()):
        it = layout.itemAt(i)
        sp, wd = it.spacerItem(), it.widget()
        if sp is not None:
            if layout.stretch(i) > 0 or sp.expandingDirections() & Qt.Horizontal:
                return                         # c'è già uno spazio elastico
            continue                           # spaziatura fissa
        grows = wd is not None and wd.sizePolicy().horizontalPolicy() != QSizePolicy.Fixed \
            and wd.maximumWidth() >= QWIDGETSIZE_MAX       # un campo con larghezza massima non prende tutto
        if layout.stretch(i) > 0 and (it.layout() is not None or grows):
            return                             # c'è già chi prende lo spazio in più
        if grows and wd.sizePolicy().horizontalPolicy() in (
                QSizePolicy.Expanding, QSizePolicy.MinimumExpanding, QSizePolicy.Ignored):
            return
    layout.setProperty("_packed", True)
    layout.addStretch(1)


def _layout_of(widget):
    """Layout (anche annidato) che contiene direttamente il widget."""
    par = widget.parentWidget()
    root = par.layout() if par is not None else None
    stack = [root] if root is not None else []
    while stack:
        lay = stack.pop()
        for i in range(lay.count()):
            it = lay.itemAt(i)
            if it.widget() is widget:
                return lay
            if it.layout() is not None:
                stack.append(it.layout())
    return None


QWIDGETSIZE_MAX = 16777215
FIELD_MIN, FIELD_MAX = 160, 560     # campi di testo: larghezza secondo il contenuto/l'esempio, entro questi limiti
SPIN_MIN, SPIN_MAX = 56, 200


def fit_field(wd):
    """Campi di testo e numerici non più larghi del necessario (non riempiono la riga). Un campo con la
    proprietà «_wide» (es. il percorso del file) resta largo."""
    from PySide6.QtWidgets import QAbstractSpinBox, QLineEdit
    if wd.property("_wide") or wd.property("_fitw") or wd.maximumWidth() < QWIDGETSIZE_MAX:
        return False                           # larghezza già decisa da chi l'ha creato
    if isinstance(wd, QAbstractSpinBox):
        wd.setFixedWidth(max(SPIN_MIN, min(SPIN_MAX, wd.sizeHint().width())))
    elif isinstance(wd, QLineEdit):
        if isinstance(wd.parentWidget(), (QComboBox, QAbstractSpinBox)):
            return False                       # il campo interno di una tendina o di uno spin

        def refit(*_):
            fm = wd.fontMetrics()
            sample = max((wd.text(), wd.placeholderText()), key=len)
            wd.setFixedWidth(max(FIELD_MIN, min(FIELD_MAX, fm.horizontalAdvance(sample) + 28)))
        refit()
        wd.textChanged.connect(refit)          # segue il testo mentre si scrive (nome, percorso…)
    else:
        return False
    wd.setProperty("_fitw", True)
    return True


def tame_combos(widget):
    """Tendine larghe quanto la voce scelta, campi di testo e numerici non più larghi del necessario, tutti
    raggruppati a sinistra nelle loro righe."""
    from PySide6.QtWidgets import QAbstractSpinBox, QLineEdit
    done = set()
    items = list(widget.findChildren(QComboBox))
    for cb in items:
        fit_combo(cb)
    items += [x for x in widget.findChildren(QLineEdit) if fit_field(x)]
    items += [x for x in widget.findChildren(QAbstractSpinBox) if fit_field(x)]
    for wd in items:
        lay = _layout_of(wd)
        if lay is not None and id(lay) not in done:
            done.add(id(lay))
            _pack_left(lay)
