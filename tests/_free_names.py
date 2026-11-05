"""_free_names.py -- which modules read a global they never bind.

Kept out of test_free_names.py so that file stays under the 100-line limit, the
same reason tests/_scan.py exists. Not itself a test module.
"""
import builtins
import pathlib
import symtable
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tests._scan import LAYERS, ROOT

# Names a module gets without importing them. `__file__` and friends are injected
# by the import machinery, not by the source.
INJECTED = {"__file__", "__name__", "__doc__", "__package__", "__spec__",
            "__loader__", "__builtins__", "__path__", "__dict__", "__annotations__",
            "__debug__", "WindowsError", "self"}


def undefined_names(path):
    """Global names `path` reads but never binds: not defined, imported or builtin."""
    src = path.read_text(encoding="utf-8")
    try:
        top = symtable.symtable(src, str(path), "exec")
    except SyntaxError as e:
        return [f"syntax error: {e}"]

    out = []

    def walk(table, bound_outer):
        # A name is satisfiable if this scope binds it, an enclosing scope binds
        # it, or it is a builtin. `symtable` reports is_global() for a name the
        # compiler will look up in the module/global namespace.
        for sym in table.get_symbols():
            name = sym.get_name()
            if not sym.is_referenced():
                continue
            if name in INJECTED or name in bound_outer:
                continue
            if sym.is_parameter() or sym.is_assigned() or sym.is_imported():
                continue
            if sym.is_local() or sym.is_free():
                continue
            # `builtins`, NOT `__builtins__`: inside a module the latter is a
            # DICT, so `dir(__builtins__)` returns dict methods and every real
            # builtin gets reported -- which buried the one finding that mattered
            # under 200 lines of `print`, `len` and `str`.
            if hasattr(builtins, name):
                continue
            out.append(name)
        for child in table.get_children():
            walk(child, bound_outer | {s.get_name() for s in table.get_symbols()})

    walk(top, set())
    return sorted(set(out))


def modules():
    for layer in LAYERS:
        base = ROOT / layer
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            yield p


