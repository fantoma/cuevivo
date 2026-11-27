"""Nome storico del pacchetto: «import cuestage…» (plugin scritti prima della rinomina) porta a «cuevivo…».

install() aggiunge un cercatore di moduli: cuestage e cuestage.X diventano gli stessi oggetti di cuevivo e
cuevivo.X (stesse classi, quindi issubclass(…, MixerDriver) continua a valere). Si chiama all'avvio e prima di
caricare i plugin.
"""
import importlib
import importlib.abc
import importlib.util
import sys

OLD = "cuestage"
NEW = __name__.rpartition(".")[0] or "cuevivo"


class _Alias(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, name, path=None, target=None):
        if name == OLD or name.startswith(OLD + "."):
            return importlib.util.spec_from_loader(name, self, is_package=name == OLD)
        return None

    def create_module(self, spec):
        return None                                     # modulo provvisorio: exec_module lo sostituisce

    def exec_module(self, module):
        real = importlib.import_module(NEW + module.__name__[len(OLD):])
        sys.modules[module.__name__] = real             # l'import restituisce quello che c'è in sys.modules


def install():
    if not any(isinstance(f, _Alias) for f in sys.meta_path):
        sys.meta_path.insert(0, _Alias())
