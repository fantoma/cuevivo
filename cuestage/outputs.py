"""Comandi verso i dispositivi esterni (mixer, regie video, proiettori, OSC e MIDI in uscita).

Su un'istanza in RIDONDANZA collegata al master i comandi esterni sono sospesi: li manda solo il master, così
mixer, regie e proiettori non ricevono tutto due volte. Appena il master è perso (o l'istanza viene promossa o
scollegata) ripartono. Il pannello principale lo segnala in arancione sopra al volume master.
"""
from concurrent.futures import Future

_held = False


def hold(on):
    """Sospende (True) o riattiva (False) i comandi verso i dispositivi esterni."""
    global _held
    _held = bool(on)


def held():
    return _held


_secondary = False


def set_secondary(on):
    """Questa istanza è collegata come slave (non di ridondanza) a un master: mostra sul suo schermo anche i
    layer «solo anteprima» (testi «non inviare allo schermo master»)."""
    global _secondary
    _secondary = bool(on)


def secondary():
    return _secondary


def done_future(result=None):
    """Future già concluso: per chi aspetta il risultato di un comando che non è partito."""
    f = Future()
    f.set_result(result)
    return f
