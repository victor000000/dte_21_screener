"""split_lib.py — AST helpers behind scripts/split_module.py.

Split out so both files stay under the 100-line limit this repo enforces on
every Python file, including its own tooling.

The load-bearing idea: a definition is moved as its EXACT source span
(`ast.get_source_segment`), never by re-indenting or re-wrapping lines. A
multi-line SQL literal's continuation lines are string CONTENT, and a transform
that treats them as indentation produces code that still parses and has been
silently corrupted -- the failure that destroyed 152,304 rows here.
"""
import ast
import hashlib
from collections import Counter


def top_level(path):
    """{name: (node, exact source text)} for every named top-level statement."""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.Assign):
            # TUPLE TARGETS COUNT. `A, B = 1, 2` is a real pattern here -- the
            # shared constants were declared that way before they were folded --
            # and registering neither name meant such a symbol could never be
            # moved, and every spec naming it failed as "not in source".
            names = []
            for t in node.targets:
                names += [e.id for e in (t.elts if isinstance(t, ast.Tuple) else [t])
                          if isinstance(e, ast.Name)]
        else:
            names = []
        for n in names:
            out[n] = (node, ast.get_source_segment(src, node))
    return src, tree, out


def literal_hashes(text):
    """Hashes of every multi-line string constant in `text`, or None if it will not parse.

    The same quantity scripts/restructure_strings.py hashes, so a split verified
    here is verified by the same rule the repo already trusts.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "\n" in node.value:
                out.append(hashlib.sha256(node.value.encode()).hexdigest()[:16])
    return sorted(out)


def symbols_of(spec):
    """Every symbol the spec assigns, in a stable order."""
    return [n for m in spec["modules"].values()
            for n in (m["symbols"] if isinstance(m, dict) else m)]


def duplicate_assignments(spec):
    return [n for n, c in Counter(symbols_of(spec)).items() if c > 1]


def render(module, names, defs, imports):
    """The module's text: a one-line docstring, its imports, then verbatim bodies."""
    body = "\n\n\n".join(defs[n][1] for n in names)
    text = f'"""{module}.py — see the package docstring."""\n{imports}\n\n{body}\n'
    return text.replace("\n\n\n\n", "\n\n\n")
