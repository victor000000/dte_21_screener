"""shim_status.py — which compatibility shims are still referenced, and which are dead.

WHY THIS EXISTS. Every shim carries the instruction:

    Delete this file once `grep -rn "<name>" scripts/ apps/ core/` shows no references left.

That instruction cannot be followed:
  * it greps `core/`, which no longer exists (the layer restructure removed it);
  * it is SELF-MATCHING -- the shim's own docstring contains <name>, so the grep
    always finds the file it is asking about; and
  * it also matches the real module's own usage example, which names the old
    `scripts/<name>.py` invocation. So every shim looks referenced forever.

This asks the question properly: import/execute sites, excluding a file's own
self-description.

    python scripts/shim_status.py            # table: shim -> target -> references
    python scripts/shim_status.py --dead     # only the deletable ones

A shim is DEAD when nothing outside itself and outside its target's own header
mentions its name -- i.e. no .py does `import <name>`, no shell script runs
`scripts/<name>.py`, and no doc points at it.
"""
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHIM_DIRS = ["scripts", "apps"]


def shim_files():
    """(shim_path, dotted_target) for every compatibility shim in the tree."""
    for d in SHIM_DIRS:
        for p in sorted((ROOT / d).rglob("*.py")):
            if "__pycache__" in p.parts or p.name == "__init__.py":
                continue
            text = p.read_text(errors="replace")
            if "COMPATIBILITY SHIM" not in text[:1200]:
                continue
            m = re.search(r'runpy\.run_module\(\s*"([\w.]+)"', text)
            if m:
                yield p, m.group(1)


def references_to(stem, dotted, shim_path, target_path):
    """Files that reference `stem`/`dotted`, excluding self-description."""
    hits = []
    exts = ("*.py", "*.sh", "*.md", "*.toml")
    for pat in exts:
        for p in ROOT.rglob(pat):
            if "__pycache__" in p.parts or ".git" in p.parts:
                continue
            if p == shim_path:
                continue                        # the shim's own docstring
            try:
                text = p.read_text(errors="replace")
            except OSError:
                continue
            # The target module's OWN header names the old invocation; that is a
            # usage example, not a dependency.
            if target_path and p == target_path:
                continue
            if re.search(rf"\b{re.escape(stem)}\b", text) or dotted in text:
                hits.append(str(p.relative_to(ROOT)))
    return hits


def main():
    only_dead = "--dead" in sys.argv
    rows, dead = [], []
    for shim, dotted in shim_files():
        target = ROOT / (dotted.replace(".", "/") + ".py")
        refs = references_to(shim.stem, dotted, shim, target)
        rows.append((shim.stem, dotted, refs))
        if not refs:
            dead.append(shim.stem)

    if not only_dead:
        print(f"{len(rows)} shim(s):\n")
        for stem, dotted, refs in rows:
            mark = "DEAD " if not refs else "     "
            print(f"  {mark}{stem:<28} -> {dotted:<44} {len(refs)} ref(s)")
            for r in refs[:2]:
                print(f"        {r}")

    print(f"\n{len(rows)} shims, {len(dead)} with no references outside themselves")
    if dead:
        print("  deletable:", ", ".join(sorted(dead)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
