"""restructure_strings.py — hash every multi-line string literal in the repo.

WHY THIS EXISTS. An earlier version of the layer migration indented code lines,
which also re-indented continuation lines *inside multi-line string literals*.
The SQL still had valid syntax as far as Python was concerned, so `ast.parse()`
passed, the modules imported, and the corruption was invisible until someone
read the query. The lesson recorded in README.md:

    "A naive line-prefix wrap corrupts multi-line SQL string literals --
     continuation lines are string content, not indentation. Verify string
     constants against git HEAD, not just the AST, before trusting any
     mechanical transform."

So this is the check that the AST cannot make. It hashes the CONTENT of every
multi-line string constant, keyed by filename (files keep their names when
moved, so a move is a no-op here and an edit shows up as a diff).

    python scripts/restructure_strings.py write plans/restructure_strings_before.json
    python scripts/restructure_strings.py diff  plans/restructure_strings_before.json

A file present before and after must show an identical list of hashes. New keys
(compatibility shims) are reported separately, not as failures.
"""
import ast
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Derived, not hardcoded. A hardcoded list rots silently the moment a new layer
# exists: with `shared/` missing, the first move made this scanner stop seeing
# shared/net.py entirely and report its literals as LOST -- a false alarm caused
# by the checker, not the move. (Same failure class as check_all.sh's
# REPO_PKGS list, which is why that one is a single named variable now.)
# market_data/ is a separate subproject with its own conventions.
LAYERS = ("core", "apps", "scripts", "market_data", "shared", "data", "compute", "datasources")
SCAN_DIRS = [d for d in LAYERS if (ROOT / d).is_dir()]


def multiline_strings(path):
    """Hashes of every string constant in `path` that spans more than one line."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError as e:
        return ["__SYNTAX_ERROR__: " + repr(e)[:120]]
    out = []
    for node in ast.walk(tree):
        # Constant covers py3.8+; JoinedStr (f-strings) is excluded on purpose --
        # its parts are expressions, and an f-string's literal chunks being
        # reindented is a different failure than a SQL body being reindented.
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "\n" in node.value:
                h = hashlib.sha256(node.value.encode("utf-8")).hexdigest()[:16]
                out.append(h)
    return sorted(out)


def scan():
    """{basename: sorted multiset of literal hashes across every file with that name}.

    Keyed by BASENAME, not full path, because a move must be a no-op here: the
    file's content does not change when it changes directory. But the value is
    the MERGED multiset of every file sharing that name -- not one file's list.

    That merging is load-bearing. Keying one-file-per-name silently loses data:
    `core/quant/bs.py` and the shim `scripts/bs.py` share a basename, so a plain
    dict keeps whichever was written last and the other becomes invisible. All 85
    shims collide with their targets this way, which would have made this check
    blind to precisely the files the restructure moves. (Caught by perturbing a
    docstring by one space and watching the detector report "no changes".)
    """
    data = {}
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            data.setdefault(p.name, []).extend(multiline_strings(p))
    return {k: sorted(v) for k, v in data.items()}


def cmd_write(dest):
    data = scan()
    total = sum(len(v) for v in data.values())
    dest = pathlib.Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    print(f"wrote {dest} — {len(data)} files, {total} multi-line string literals")


def _multiset_diff(old, new):
    """Hashes in old but missing from new, and vice versa (multiset, not set)."""
    from collections import Counter
    co, cn = Counter(old), Counter(new)
    lost = list((co - cn).elements())
    gained = list((cn - co).elements())
    return sorted(lost), sorted(gained)


def _repo_multiset(data):
    """Every literal hash in the repo as ONE multiset, ignoring which file holds it.

    WHY THIS MODE EXISTS. The per-basename diff answers "did this FILE's content
    change", which is the right question for a MOVE -- the file keeps its name, so
    its literals stay under the same key. It is the wrong question for a SPLIT:
    splitting a module into a package relocates its literals from
    build_positions.py into __main__.py, spot.py and the rest, so the basename key
    loses them and EVERY split reports LOST -- by construction, not because
    anything was corrupted.

    The alternative, re-baselining after each split, silences that by making the
    current state the new baseline -- so the one time a literal really was dropped
    rather than moved, the corruption is laundered into the record and invisible
    forever. That is the exact outcome this detector exists to prevent.

    Flattening keeps the detection that matters: a multi-line literal whose
    CONTENT changed, or one that vanished entirely. Relocation becomes a no-op.
    The per-basename view is still printed underneath as the attribution record --
    it shows which hashes left which name -- but it does not gate.
    """
    from collections import Counter
    c = Counter()
    for v in data.values():
        c.update(v)
    return c


def cmd_diff_repo(ref, explain=False):
    before = _repo_multiset(json.loads(pathlib.Path(ref).read_text()))
    after = _repo_multiset(scan())
    lost = list((before - after).elements())
    gained = list((after - before).elements())

    if lost:
        print(f"  ! {len(lost)} multi-line literal(s) LOST repo-wide — content changed "
              f"or a file was removed")
        for h in lost[:5]:
            print(f"      {h}")
    if gained:
        print(f"  + {len(gained)} literal(s) gained repo-wide "
              f"({'expected: new files' if len(gained) < 40 else 'large — check'})")

    if explain:
        # Which NAMES lost and gained. Not gating: during a split this is exactly
        # the expected signature, and it is the evidence that the literals moved
        # rather than disappeared.
        old_names, new_names = json.loads(pathlib.Path(ref).read_text()), scan()
        moved = []
        for name in sorted(set(old_names) | set(new_names)):
            l, g = _multiset_diff(old_names.get(name, []), new_names.get(name, []))
            if l or g:
                moved.append(f"      {name}: {len(l)} lost, {len(g)} gained")
        if moved:
            print("    per-name attribution (expected during a split):")
            for m in moved[:14]:
                print(m)
            if len(moved) > 14:
                print(f"      ... and {len(moved) - 14} more names")

    ok = not lost
    print("\nno literal content changed repo-wide" if ok else
          "\nLOST LITERALS FOUND — investigate before continuing")
    return 0 if ok else 1


def cmd_diff(ref):
    before = json.loads(pathlib.Path(ref).read_text())
    after = scan()

    lost_report, gained_report = [], []
    for name in sorted(set(before) | set(after)):
        old, new = before.get(name, []), after.get(name, [])
        lost, gained = _multiset_diff(old, new)
        if lost:
            # A literal that existed before and does not now. This is the
            # corruption mode: content changed inside a multi-line string.
            lost_report.append((name, lost))
        if gained:
            # Expected for a new shim; a genuine concern if no file was added.
            gained_report.append((name, gained))

    for name, lost in lost_report:
        print(f"  ! {name}: {len(lost)} literal(s) LOST — content changed or file removed")
        for h in lost[:3]:
            print(f"      {h}")
    for name, gained in gained_report:
        tag = "(new file)" if name not in before else "(EDITED, or a new file with this name)"
        print(f"  + {name}: {len(gained)} literal(s) gained {tag}")

    ok = not lost_report
    if ok and gained_report:
        print(f"\nno literals lost ({len(gained_report)} names gained literals — expected "
              f"for new shims; confirm each is a NEW file, not an edit)")
    elif ok:
        print("\nno string-literal changes")
    else:
        print("\nLOST LITERALS FOUND — investigate before continuing")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    args = sys.argv[1:]
    explain = "--explain" in args
    args = [a for a in args if a != "--explain"]
    scope = "basename"
    if "--scope" in args:
        i = args.index("--scope")
        if i + 1 >= len(args):
            print("--scope needs a value: basename | repo")
            sys.exit(2)
        scope = args[i + 1]
        del args[i:i + 2]
    if len(args) < 2 or scope not in ("basename", "repo"):
        print(__doc__)
        sys.exit(2)
    mode, arg = args[0], args[1]
    if mode == "write":
        cmd_write(arg)
    elif mode == "diff":
        if scope == "repo":
            sys.exit(cmd_diff_repo(arg, explain=explain))
        sys.exit(cmd_diff(arg))
    else:
        print(__doc__)
        sys.exit(2)
