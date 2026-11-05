"""split_rewrite.py — put the moved spans back into the source file.

Split out of split_lib.py so both files stay under the 100-line limit.
"""
import ast


def rewrite_source(src_path, defs, moved, keep, imports):
    """Remove the moved spans from the source and add the import block.

    THE OTHER HALF OF A MOVE. Writing the modules without removing what they came
    from leaves two copies of every function -- which still runs, so the gate
    stays green and the duplication is invisible. The source keeps its NAME
    (callers, the shim and the path invocations all point at it), loses the moved
    spans, and gains the imports the symbols it kept still need.
    """
    src = src_path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = src.splitlines()
    spans = sorted((defs[n][0].lineno, defs[n][0].end_lineno) for n in moved)
    out, i = [], 1
    while i <= len(lines):
        span = next((s for s in spans if s[0] == i), None)
        if span:
            i = span[1] + 1
            continue
        out.append(lines[i - 1])
        i += 1
    if imports:
        # AFTER THE LAST HEADER IMPORT, and specifically NOT after the last kept
        # function. The first version anchored on the kept symbols, which put the
        # block below `if __name__ == "__main__": main()` -- so running the script
        # called main() and hit a NameError on the first moved symbol, while every
        # check stayed green: py_compile cannot see a runtime lookup, the import
        # sweep never executes the guard, the free-names check sees the names as
        # imported, and --help exits before any of it. Only RUNNING the file finds
        # it, which is what the guard-last test in tests/ now does statically.
        anchor = 0
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)) and node.lineno < len(lines):
                anchor = max(anchor, node.end_lineno)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                break
        out.insert(min(anchor, len(out)), "\n" + imports)
    src_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return len(lines) - len(out)
