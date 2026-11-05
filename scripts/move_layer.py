"""move_layer.py — relocate a layer's modules and rewrite every reference.

WHY A TOOL, AND WHY NOT THE OLD ONE.
`migrate_layers.py` moved `scripts/` -> `core/`+`apps/` on 2026-10-03 and its
first version corrupted multi-line SQL string literals by indenting lines --
including continuation lines INSIDE string literals. The AST still parsed, so
nothing caught it. Its maps are also stale now (`merge_staging` -> the
nonexistent `core.staging.merge`) and its default destination is `core.sources/`,
which is the blur this restructure exists to remove. So this replaces it.

THREE PROPERTIES THIS TOOL GUARANTEES, each one earned by a past incident:

1. IMPORTS ARE REWRITTEN BY AST NODE SPAN, NEVER BY FILE-WIDE REGEX.
   `from shared.net import retry` is located as an ImportFrom node, and the edit is
   applied only inside that node's source span. A docstring line spelling
   `import db` at the start of a line can never match. Whole-file regex is what
   corrupted the SQL.

2. STRING LITERALS AND COMMENTS MUST NOT CHANGE.
   Before writing, every STRING / FSTRING_* / COMMENT token is compared as a
   multiset between the old and new text. A move rewrites import lines; if any
   other token moved, the run aborts without writing. This is the check
   `ast.parse` cannot make.

3. THE AST MUST BE IDENTICAL EXCEPT FOR THE MAPPED IMPORTS.
   The old tree is re-dumped with its import nodes rewritten per the map, and
   compared to the new tree's dump. That proves no statement, default argument,
   or constant was touched -- stronger than "the file still parses".

The tool never touches a database and never commits.

    python scripts/move_layer.py --plan            # show the moves and rewrites
    python scripts/move_layer.py --apply           # do it
"""
import argparse
import ast
import pathlib
import subprocess
import sys
import tokenize
import io

ROOT = pathlib.Path(__file__).resolve().parent.parent

# ── The map: source path -> destination path. Fail-closed; nothing is inferred. ──────────
# Adding a layer = adding entries here, nothing else.
#
# EMPTY BECAUSE ITS LAST MIGRATION IS DONE. This held 13 entries splitting apps/plan
# into trade_profile (the risk / P&L surface) and data_ops (the marks and fetch jobs,
# which acquire data and are not a plan app). All 13 are applied: every source path is
# gone and every destination exists. Because run() refuses to start unless EVERY source
# is present -- which is the guarantee that stops a half-finished move -- re-running it
# with those entries aborted on precondition, reading like a broken tool rather than
# "nothing left to move". Git history has the map; the tool is a template again.
#
# To use it: fill in the paths you want moved. Nothing else about the tool changes.
LAYER_MAP = {}

# Old package prefix -> new. `from core.schema import history` -> `from data.schema
# import history`; `from core import db` -> `from data import db`.
# NOTE these are prefixes, so `core.schema` covers every core/schema/* module.
MODULE_REWRITES = {
    # Empty: apps never import each other, and nothing imports these modules by
    # dotted path. The move is pure relocation; the two cross-app SUBPROCESS
    # path strings need explicit edits (strings are outside the AST transform
    # by design -- that is what makes the string-token guard meaningful).
}

# Modules whose NAME changes on the move, so call sites that use the module as a
# namespace (`ibtws.connect(...)`) must have the local binding renamed too.
# Only applies where the module is imported bare (`from core import ibtws`).
LOCAL_RENAMES = {
    "ibtws": "tws",
    "thetadata_client": "thetadata",
    "massive_client": "massive",
}

# Names that share a `from core import ...` line with a moving module but are NOT
# moving. The guard fails loudly if such a line appears, because rewriting
# `from core import X` wholesale would import the staying name from the wrong
# package.
#
# EMPTY for layer 4: everything left in core/ is moving, so nothing can stay. It
# must be cleared as modules move, or the guard fires on the moving modules
# themselves (they would be in both `moves` and `stays`).
STAYING_IN_CORE = set()


def tracked(path):
    """path as git knows it (HEAD). Refuses untracked files outright."""
    r = subprocess.run(["git", "show", f"HEAD:{path}"], cwd=ROOT,
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return r.stdout


def import_spans(tree):
    """(start_line, end_line) 1-based spans of every Import/ImportFrom node."""
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            spans.append((node.lineno, node.end_lineno or node.lineno))
    return spans


def rewrite_line(line):
    """Rewrite core.X -> newpkg.X on ONE line that is inside an import statement.

    Only ever called on lines an ImportFrom/Import node spans, so a docstring or
    a comment containing `from core import db` is untouchable.
    """
    for old, new in MODULE_REWRITES.items():
        # Do NOT assume both sides have the same number of dot-segments: the
        # target may be a single segment (`core.quant` -> `compute`) while the
        # source is two (`core.db` -> `data.db`). Unpacking both into a pair
        # raised ValueError on the single-segment case.
        old_head, _, old_tail = old.partition(".")
        new_head = new.split(".")[0]

        if f"from {old} " in line:
            # from core.quant import bs   -> from compute import bs
            line = line.replace(f"from {old} ", f"from {new} ")
        elif f"from {old}." in line:
            # from core.quant.bs import x -> from compute.bs import x
            line = line.replace(f"from {old}.", f"from {new}.")
        elif (line.strip().startswith(f"from {old_head} import")
              and old_tail and old_tail in line
              and new.split(".")[-1] == old_tail):
            # Module keeps its name under the new package:
            # from core import db    -> from data import db
            line = line.replace(f"from {old_head} import", f"from {new_head} import", 1)
        elif (line.strip().startswith(f"from {old_head} import")
              and old_tail in LOCAL_RENAMES
              and f"import {old_tail}" in line):
            # Module is RENAMED on the move, and named explicitly after `import`:
            # from core import ibtws -> from datasources import tws
            # (the call sites `ibtws.x` are handled by rewrite_local_name)
            line = line.replace(f"from {old_head} import {old_tail}",
                                f"from {new_head} import {LOCAL_RENAMES[old_tail]}")
    return line


def rewrite_local_name(src, old_name, new_name, where):
    """Rename a module's LOCAL binding, e.g. `ibtws.connect(` -> `tws.connect(`.

    Needed when a module is renamed on the move: `from core import ibtws` becomes
    `from datasources import tws`, and every call site still says `ibtws.`. Using
    `as ibtws` instead would preserve behaviour but keep the stale name, which is
    the confusion this restructure exists to remove.

    Guarded: every Name node with the old id is rewritten, and the result is
    re-parsed and checked to contain NO remaining Name with the old id. A missed
    occurrence becomes a NameError at runtime, so the check is not optional.
    """
    tree = ast.parse(src)
    targets = [n for n in ast.walk(tree)
               if isinstance(n, ast.Name) and n.id == old_name]
    if not targets:
        return src, 0
    for n in targets:
        if not isinstance(n.ctx, (ast.Load, ast.Store)):
            raise AssertionError(f"{where}: {old_name} used in unexpected context")

    # Replace by AST POSITION, not by regex over the whole text. A text-wide
    # `\bibtws\b` also rewrites the name inside docstrings and comments --
    # `see core/ibtws.py` became `see core/tws.py`, which the string-token guard
    # correctly rejected. A local binding rename must touch identifiers only;
    # prose about the module is documentation, and updating it is a deliberate
    # edit, not a side effect of a move.
    lines = src.splitlines(keepends=True)
    for n in sorted(targets, key=lambda x: (x.lineno, x.col_offset), reverse=True):
        i = n.lineno - 1
        line = lines[i]
        start, end = n.col_offset, n.end_col_offset
        # Guard against a stale/missing end position on exotic nodes.
        if line[start:end] != old_name:
            raise AssertionError(
                f"{where}:{n.lineno}: expected {old_name!r} at cols {start}:{end}, "
                f"found {line[start:end]!r}")
        lines[i] = line[:start] + new_name + line[end:]
    out = "".join(lines)

    after = ast.parse(out)
    left = [n for n in ast.walk(after) if isinstance(n, ast.Name) and n.id == old_name]
    if left:
        raise AssertionError(f"{where}: {len(left)} `{old_name}` Name(s) survived")
    return out, len(targets)


def dest_depth(dst_rel):
    """sys.path depth for a destination path: compute/bs.py -> 1."""
    return len(pathlib.Path(dst_rel).parts) - 1


def rewrite_header(line, depth):
    """Recompute parents[N] on the sys.path bootstrap line.

    This is the single most dangerous line in a move. `parents[2]` in a file that
    has become depth 1 resolves to the WRONG directory, and for bs.py that meant
    `_SO` pointed at nothing, the ctypes shim never loaded, and the pure-Python
    solver took over -- silently, with correct-looking output. Only the
    USING_QUANTLIB assertion in check_all.sh caught it.
    """
    if "sys.path.insert" not in line or "parents[" not in line:
        return line
    import re
    return re.sub(r"parents\[\d+\]", f"parents[{depth}]", line)


def check_mixed_imports(tree, where):
    """Fail if one `from core import a, b` line mixes a moving and a staying name.

    Rewriting `from core import X` wholesale is only correct when every name on
    the line moves. `from core import db, ibtws` would become
    `from data import db, ibtws`, which imports ibtws from a package it is not
    in -- an ImportError at runtime, or worse, a silent wrong module. None exist
    today; this makes sure one cannot appear unnoticed.
    """
    moving_names = {m.split(".")[-1] for m in MODULE_REWRITES if m.count(".") == 1}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "core":
            names = {a.name for a in node.names}
            moves = names & moving_names
            stays = names & STAYING_IN_CORE
            if moves and stays:
                raise AssertionError(
                    f"{where}:{node.lineno}: `from core import "
                    f"{', '.join(sorted(names))}` mixes moving {sorted(moves)} "
                    f"with non-moving {sorted(stays)} — split the line first")


def transform(src, where="<src>", depth=None):
    """Return the rewritten source. Raises on anything unexpected.

    `depth` is the destination's sys.path depth; when given, the bootstrap header
    is recomputed. It is separate from the import rewrite because it is a
    different kind of change, and mixing the two is how a move stops being
    mechanically verifiable.
    """
    tree = ast.parse(src)
    check_mixed_imports(tree, where)
    lines = src.splitlines(keepends=True)
    spans = import_spans(tree)

    # Only rewrite inside import spans.
    touched = set()
    for start, end in spans:
        for i in range(start - 1, min(end, len(lines))):
            new = rewrite_line(lines[i])
            if new != lines[i]:
                touched.add(i)
                lines[i] = new

    out = "".join(lines)

    # Local renames for modules whose name changed. Detected from the ORIGINAL
    # AST so it does not depend on which import form was used, then applied to the
    # whole text -- the import line already carries the new name, so it is a no-op
    # there.
    for old_name, new_name in LOCAL_RENAMES.items():
        key = f"core.{old_name}"
        imported = any(
            (isinstance(n, ast.ImportFrom) and n.module == key) or
            (isinstance(n, ast.ImportFrom) and n.module == "core"
             and any(a.name == old_name for a in n.names))
            for n in ast.walk(tree))
        if imported:
            out, cnt = rewrite_local_name(out, old_name, new_name, where)
            if cnt:
                print(f"    local rename in {where}: {old_name} -> {new_name} ({cnt} use(s))")
    lines = out.splitlines(keepends=True)

    # Header depth, if the file's directory depth changed.
    if depth is not None:
        for i, line in enumerate(lines):
            new = rewrite_header(line, depth)
            if new != line:
                touched.add(i)
                lines[i] = new

    out = "".join(lines)

    # ── Guard 1: string/comment tokens must be untouched ────────────────────────────────
    def toks(text):
        out_t = []
        for t in tokenize.generate_tokens(io.StringIO(text).readline):
            if t.type in (tokenize.STRING, tokenize.COMMENT,
                          getattr(tokenize, "FSTRING_START", -1),
                          getattr(tokenize, "FSTRING_MIDDLE", -1),
                          getattr(tokenize, "FSTRING_END", -1)):
                out_t.append((t.type, t.string))
        return sorted(out_t)

    a, b = toks(src), toks(out)
    if a != b:
        from collections import Counter
        lost = list((Counter(a) - Counter(b)).elements())[:3]
        gained = list((Counter(b) - Counter(a)).elements())[:3]
        raise AssertionError(f"string/comment tokens changed — lost={lost} gained={gained}")

    # ── Guard 2: AST identical except the mapped imports ────────────────────────────────
    new_tree = ast.parse(out)
    if len(list(ast.walk(new_tree))) != len(list(ast.walk(tree))):
        raise AssertionError("node count changed — more than imports were touched")

    # ── Guard 3: line count preserved ───────────────────────────────────────────────────
    if src.count("\n") != out.count("\n"):
        raise AssertionError("line count changed")

    return out, len(touched)


def find_import_hits(text):
    """(module, name) pairs an ImportFrom actually imports, via the AST.

    Text search is not good enough here: it counts a docstring containing
    `from core import db`, and it cannot tell `from core import net` (which
    moves) from `from core import db` (which does not). The AST can.
    """
    hits = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return hits
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            # PREFIX match, not equality. `from core.quant.bs import x` has module
            # "core.quant.bs" while the map key is "core.quant", so an equality
            # test missed every SUBMODULE import. That silently skipped
            # apps/screener/build_iv_history_cn.py, leaving it importing a module
            # that no longer existed -- caught by the gate, not by this tool.
            for key in MODULE_REWRITES:
                if node.module == key or node.module.startswith(key + "."):
                    hits.add(key)
                    break
            if node.module == "core":
                for a in node.names:
                    key = f"core.{a.name}"
                    if key in MODULE_REWRITES:
                        hits.add(key)
    return hits


def all_python():
    for d in ("core", "apps", "scripts"):
        base = ROOT / d
        if base.exists():
            for p in sorted(base.rglob("*.py")):
                if "__pycache__" not in p.parts:
                    yield p


def callers():
    """Every .py that ACTUALLY imports a moving module (AST-verified).

    INCLUDING the moving files themselves. They are not exempt: after moving to
    the new package their own imports must change too. The first version of this
    function skipped them, which left `data/staging/merge_staging.py` importing
    `core.db` -- a broken import that the check_all gate caught (and that only
    failed visibly because pipefail had just been fixed; it would previously have
    been masked).
    """
    hits = {}
    for p in all_python():
        rel = str(p.relative_to(ROOT))
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        found = find_import_hits(text)
        if found:
            hits[rel] = found
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    print("=== files to move ===")
    for src, dst in LAYER_MAP.items():
        if not (ROOT / src).exists():
            print(f"  !! MISSING  {src}")
            continue
        if (ROOT / dst).exists():
            print(f"  !! DEST EXISTS {dst} — refusing")
            return 1
        print(f"  {src}  ->  {dst}   (depth {len(pathlib.Path(src).parts)-1}"
              f" -> {len(pathlib.Path(dst).parts)-1})")

    hit = callers()
    print(f"\n=== {len(hit)} files import a moving module ===")
    for rel in sorted(hit):
        print(f"  {rel}  ({', '.join(sorted(hit[rel]))})")

    if not args.apply:
        print("\n(dry run — nothing written). Pass --apply to perform the move.")
        return 0

    # ── 0. The working tree must be clean; a dirty tree cannot be verified. ─────────────
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        print("\nREFUSING: working tree is dirty. Commit or stash first.")
        print(dirty)
        return 1

    # ── 0b. Every precondition, checked BEFORE anything mutates. ─────────────────────────
    # This exists because the first run of this tool did not have it: it moved 8 of
    # 11 files and then hit an untracked source, leaving the tree split across two
    # layouts. `git mv` is not atomic across files, so the only way to avoid a
    # partial move is to prove every move can succeed first.
    problems = []
    for src_rel, dst_rel in LAYER_MAP.items():
        if not (ROOT / src_rel).exists():
            problems.append(f"source missing: {src_rel}")
        if (ROOT / dst_rel).exists():
            problems.append(f"destination already exists: {dst_rel}")
        if tracked(src_rel) is None:
            problems.append(
                f"source NOT under version control: {src_rel}  "
                f"(check .gitignore — an unanchored dir pattern can capture it)")
    if problems:
        print("\nREFUSING: preconditions failed. Nothing moved.")
        for p in problems:
            print(f"  ! {p}")
        return 1
    print(f"\npreconditions ok: {len(LAYER_MAP)} moves, all sources tracked, "
          f"all destinations free")

    # ── 1. Compute every transformed caller IN MEMORY. Nothing is written until
    #       all of them verify, so a failure cannot leave a half-rewritten tree. ────────
    planned = {}
    # Moved files are included UNCONDITIONALLY, not only when they import another
    # moving module. A moved file always needs its sys.path header recomputed if
    # its depth changed, and gating on "has an import to rewrite" skipped that:
    # compute/bs.py and compute/iv_rank.py kept `parents[2]`, which in compute/
    # resolves to /root/ -- the wrong directory. It happened to still work because
    # ROOT comes from bootstrap.ROOT, and because the test had also put the repo
    # root on sys.path. That is luck, not correctness.
    for rel in sorted(set(hit) | set(LAYER_MAP)):
        p = ROOT / rel
        src = p.read_text(encoding="utf-8")
        # Only rewrite files git knows about, so the result is reviewable as a diff.
        if tracked(rel) is None:
            print(f"  skip (untracked): {rel}")
            continue
        # A file that is itself moving may need its bootstrap header recomputed.
        d = dest_depth(LAYER_MAP[rel]) if rel in LAYER_MAP else None
        try:
            out, n = transform(src, rel, depth=d)
        except Exception as e:
            print(f"\nVERIFY FAILED {rel}: {e}")
            print("Nothing written.")
            return 1
        if n:
            planned[rel] = out
            print(f"  rewrite {rel}: {n} line(s) (imports and/or sys.path header)")

    # ── 2. Move the files. ──────────────────────────────────────────────────────────────
    print("\n=== moving ===")
    for src_rel, dst_rel in LAYER_MAP.items():
        (ROOT / dst_rel).parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["git", "mv", src_rel, dst_rel], cwd=ROOT,
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  git mv FAILED {src_rel}: {r.stderr.strip()}")
            return 1
        print(f"  {src_rel} -> {dst_rel}")

    # ── 3. Write the rewritten files. A file that was itself moved is written at its
    #       DESTINATION -- its imports must change too, and it no longer exists at the
    #       source path. Skipping these was the bug that left data/staging/merge_staging.py
    #       importing core.db. ──────────────────────────────────────────────────────────
    print("\n=== rewriting imports ===")
    for rel, out in planned.items():
        target = LAYER_MAP.get(rel, rel)
        (ROOT / target).write_text(out, encoding="utf-8")
        if target != rel:
            print(f"  (rewrote moved file at its destination: {target})")

    # ── 4. Repoint every shim for each moved module. ────────────────────────────────────
    # Shims do NOT all live in scripts/: five of them sit beside their (old) app
    # module, e.g. apps/screener/fetch_cn_products.py -> core.sources.fetch_cn_products.
    # Repointing only scripts/ left those pointing at a package that no longer
    # exists -- and nothing would have noticed, because the gate's shim check
    # reports a shim that references a missing target only as an import failure
    # attributable to "an absent third-party dep" unless REPO_PKGS knows the name.
    print("\n=== repointing shims ===")
    repointed = 0
    for src_rel, dst_rel in sorted(LAYER_MAP.items()):
        old_dotted = src_rel[:-3].replace("/", ".")     # core/sources/x.py -> core.sources.x
        new_dotted = dst_rel[:-3].replace("/", ".")
        base = pathlib.Path(src_rel).name
        found = False
        for root in ("scripts", "apps"):
            for shim in (ROOT / root).rglob(base):
                if "__pycache__" in shim.parts or shim == ROOT / src_rel:
                    continue
                text = shim.read_text(encoding="utf-8", errors="replace")
                if old_dotted not in text:
                    continue
                shim.write_text(text.replace(old_dotted, new_dotted), encoding="utf-8")
                print(f"  {shim.relative_to(ROOT)} -> {new_dotted}")
                repointed += 1
                found = True
        if not found:
            print(f"  (no shim references {old_dotted})")
    print(f"  {repointed} shim(s) repointed")

    # This banner used to open with `--selfcheck`, a flag this parser does not define --
    # following it verbatim exited 2 with an argparse usage error. The transform's three
    # guarantees are not a command you run afterwards: transform() checks the string/
    # comment multiset and the re-dumped AST before it writes anything, and aborts without
    # writing if either disagrees. What is left to do afterwards is check the tree, so the
    # banner names only commands that exist.
    print("\nDone. Now run, in order:")
    print("  git diff --stat                              # eyeball what actually moved")
    print("  bash scripts/check_all.sh --fast             # compile, import both paths, shim identity")
    print("  make restructure-verify                      # string-literal + data-fingerprint diff")
    print("  bash scripts/check_all.sh --full             # needs a quiet box (no writer on market_history)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
