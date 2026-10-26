"""Which paths a short inline Python program writes, read from its syntax tree.

The Bash screen used to treat every path in a `python -c` or heredoc program as a possible write once
the code contained `open(..., 'w')`, `shutil` or `write_text`, so a script that reads the archive and
copies into a new investigation was refused. Here only the paths that reach a writing call count:
the destination of a copy, the file opened for writing, the directory created. A path is followed
through simple assignments and `for` loops; `a / b` keeps the left side's paths, and `.name`-like
attributes carry none. A write whose target cannot be traced to any literal makes the result
`None`, and the caller falls back to every path in the code, as before.
"""

from __future__ import annotations

import ast

_READ_ONLY_ATTRS = {"name", "stem", "suffix", "suffixes", "parts"}
_COPY = {"copy", "copy2", "copyfile", "copytree", "copyfileobj"}
_BOTH = {"move", "rename", "replace", "renames"}
_FIRST = {"remove", "unlink", "rmdir", "removedirs", "rmtree", "makedirs", "mkdir", "truncate", "chmod", "chown"}
_METHODS = {"write_text", "write_bytes", "mkdir", "touch", "unlink", "rmdir", "chmod"}
_WRITE_MODE_CHARS = set("wax+")


def write_targets(code: str) -> list[str] | None:
    """Literal paths the code writes, or None when a write target cannot be traced (or it does not parse)."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return None
    env: dict[str, set[str]] = {}

    def sources(node: ast.AST | None) -> set[str]:
        if node is None:
            return set()
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return {node.value}
        if isinstance(node, ast.Name):
            return set(env.get(node.id, set()))
        if isinstance(node, ast.BinOp):
            return sources(node.left) if isinstance(node.op, ast.Div) else sources(node.left) | sources(node.right)
        if isinstance(node, ast.JoinedStr):
            lits = [v.value for v in node.values if isinstance(v, ast.Constant)]
            first = node.values[0] if node.values else None
            out = {"".join(lits)} if lits and isinstance(first, ast.Constant) else set()
            return out | (sources(first.value) if isinstance(first, ast.FormattedValue) else set())
        if isinstance(node, ast.Attribute):
            return set() if node.attr in _READ_ONLY_ATTRS else sources(node.value)
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr in ("join",) and isinstance(f.value, ast.Attribute):
                return sources(node.args[0]) if node.args else set()  # os.path.join(base, ...)
            if isinstance(f, ast.Attribute):
                return sources(f.value)  # p.with_suffix(...), p.glob(...), p.resolve()
            return set().union(*(sources(a) for a in node.args[:1])) if node.args else set()
        if isinstance(node, ast.Subscript):
            return sources(node.value)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return set().union(*(sources(e) for e in node.elts)) if node.elts else set()
        return set()

    def bind(target: ast.AST, value: set[str]) -> None:
        if isinstance(target, ast.Name):
            env[target.id] = env.get(target.id, set()) | value
        elif isinstance(target, (ast.Tuple, ast.List)):
            for t in target.elts:
                bind(t, value)

    # two passes so a name assigned after its first use in a loop body is still traced
    for _ in range(2):
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    bind(t, sources(node.value))
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value is not None:
                bind(node.target, sources(node.value))
            elif isinstance(node, (ast.For, ast.comprehension)):
                bind(node.target, sources(node.iter))
            elif isinstance(node, ast.withitem) and node.optional_vars is not None:
                bind(node.optional_vars, sources(node.context_expr))

    out: list[str] = []
    opaque = False

    def hit(expr: ast.AST | None) -> None:
        nonlocal opaque
        found = sources(expr)
        if not found:
            opaque = True
        out.extend(sorted(found))

    def mode_of(call: ast.Call, pos: int) -> str:
        m = call.args[pos] if len(call.args) > pos else next((k.value for k in call.keywords if k.arg == "mode"), None)
        return m.value if isinstance(m, ast.Constant) and isinstance(m.value, str) else ("w" if m is not None else "r")

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
        args = node.args
        if isinstance(f, ast.Name) and name == "open":
            if _WRITE_MODE_CHARS & set(mode_of(node, 1)):
                hit(args[0] if args else None)
        elif isinstance(f, ast.Attribute) and name == "open":
            if _WRITE_MODE_CHARS & set(mode_of(node, 0)):
                hit(f.value)
        elif isinstance(f, ast.Attribute) and name in _METHODS:
            hit(f.value)
        elif isinstance(f, ast.Attribute) and name == "rename" and not _module(f, "os"):  # Path.rename (str.replace is not a write)
            hit(f.value)
            hit(args[0] if args else None)
        elif name in _COPY and _module(f, "shutil"):
            hit(args[1] if len(args) > 1 else None)
        elif name in _BOTH and (_module(f, "shutil") or _module(f, "os")):
            for a in args[:2]:
                hit(a)
        elif name in _FIRST and (_module(f, "os") or _module(f, "shutil")):
            hit(args[0] if args else None)
    return None if opaque else out


def _module(f: ast.AST, mod: str) -> bool:
    return isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == mod
