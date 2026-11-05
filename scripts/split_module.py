"""split_module.py — move named top-level definitions into a package, VERBATIM.

Splitting 113 files by hand is 113 chances to reflow a line inside a multi-line
SQL literal -- the corruption mode that destroyed 152,304 rows here, which
ast.parse() cannot see because the result still parses. So a definition moves as
its exact source span, and every emitted module is checked BEFORE anything is
written: every symbol is assigned, dropped or explicitly KEPT; per module, the
emitted text carries EXACTLY the multi-line literals its symbols had (same
hashes, so a reflowed SQL continuation line fails here, not in production); and
no module exceeds the line limit.

It cannot DECOMPOSE a 265-line function; put those in `keep` for a second pass.
    uv run python scripts/split_module.py <spec.json> [--apply]

  { "source": "apps/x/y.py", "package": "apps/x/y",
    "modules": { "quotes": {"symbols": ["get_latest_price"],
                            "imports": "from data import db"} },
    "drop": ["dead_function"], "keep": ["main"] }
"""
import json
import pathlib
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import split_lib as SL  # noqa: F401
import split_rewrite

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIMIT = 100


def build(spec_path, apply=False):
    spec = json.loads(pathlib.Path(spec_path).read_text())
    src_path = ROOT / spec["source"]
    defs = SL.top_level(src_path)[2]
    wanted, drop, keep = SL.symbols_of(spec), spec.get("drop", []), spec.get("keep", [])

    missing = [n for n in wanted if n not in defs]
    if missing or SL.duplicate_assignments(spec):
        print(f"FAIL  missing from source: {missing}; "
              f"assigned twice: {SL.duplicate_assignments(spec)}")
        return 1
    unassigned = [k for k in defs if k not in wanted and k not in drop and k not in keep]
    if unassigned:
        print(f"FAIL  neither assigned, dropped nor kept: {unassigned}")
        return 1

    emitted = {}
    for module, m in spec["modules"].items():
        names = m["symbols"] if isinstance(m, dict) else m
        text = SL.render(module, names, defs, m.get("imports", "") if isinstance(m, dict) else "")
        got = SL.literal_hashes(text)
        if got is None:
            print(f"FAIL  {module}.py would not parse")
            return 1
        # Same HASHES, not the same count: a reflowed continuation line inside a
        # SQL literal changes content and is caught right here.
        want = Counter()
        for n in names:
            want.update(SL.literal_hashes(defs[n][1]) or [])
        if Counter(got) != want:
            lost, gained = want - Counter(got), Counter(got) - want
            print(f"FAIL  {module}.py literal content changed — "
                  f"{sum(lost.values())} lost, {sum(gained.values())} gained")
            for h in list(lost)[:3]:
                print(f"      lost     {h}")
            return 1
        emitted[module] = text

    over = {m: len(t.splitlines()) for m, t in emitted.items()
            if len(t.splitlines()) > LIMIT}
    if over:
        print(f"FAIL  module(s) over {LIMIT} lines: {over}")
        return 1

    print(f"OK    {len(emitted)} module(s); every moved literal verified verbatim")
    for m, t in sorted(emitted.items()):
        print(f"      {m:22} {len(t.splitlines()):>4} lines")
    if keep:
        print(f"      kept in source: {keep}")
    if not apply:
        print("\n(dry run — pass --apply to write)")
        return 0

    pkg = ROOT / spec["package"]
    pkg.mkdir(parents=True, exist_ok=True)
    for m, t in emitted.items():
        (pkg / f"{m}.py").write_text(t, encoding="utf-8")

    split_rewrite.rewrite_source(src_path, defs, wanted, keep, spec.get("source_imports", ""))
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(2)
    sys.exit(build(args[0], apply="--apply" in sys.argv))
