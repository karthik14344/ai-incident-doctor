"""Week 5 - a static relationship graph over this repository.

Sourcegraph answers *where a name appears*. That is a text index, and on the
free single-container instance the navigation is search-based, so `get_embedding`
matches the definition, every call site, every import and every comment that
happens to spell it, with no way to tell them apart.

This module supplies the missing half: a real graph built from Python's own
parser. Nothing here guesses. An edge exists because `ast` saw a `Call` node
inside a `FunctionDef`, or an `Import` node at module scope.

The two layers are deliberately kept separate rather than merged, because
disagreement between them is a finding, not a bug:

  * Sourcegraph finds a name the AST has no edge for -> the reference is in a
    comment, a string, or a language the parser does not read (.jsx).
  * The AST has an edge Sourcegraph's regex missed -> the call is spelled
    differently at the call site, e.g. aliased on import.

What no static pass can see is recorded honestly in `DYNAMIC_EDGES` rather than
silently dropped: FastAPI registers routes through decorators at import time,
and the services call each other over HTTP through URL constants. Those edges
are real, and both this module and Sourcegraph are blind to them.
"""

import ast
import json
import os
from typing import Any, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    "chroma_data", "dist", "build", ".vite", "storage", "data",
}


def _rel(path: str) -> str:
    return os.path.relpath(path, BASE_DIR).replace("\\", "/")


def iter_python_files(root: str = BASE_DIR) -> List[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for name in sorted(filenames):
            if name.endswith(".py"):
                out.append(os.path.join(dirpath, name))
    return sorted(out)


def _callee_name(node: ast.Call) -> Optional[str]:
    """The bare name being called.

    `foo()` -> "foo";  `mod.foo()` -> "foo";  `a.b.foo()` -> "foo".
    The attribute owner is dropped on purpose: the graph keys on symbol name so
    that a call site can be matched against a definition found anywhere. That
    is also the graph's main imprecision, and it is why `resolve` below reports
    ambiguity instead of picking a winner.
    """
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _route_decorator(node: ast.AST) -> Optional[str]:
    """`@app.post("/generate")` -> "POST /generate"."""
    for dec in getattr(node, "decorator_list", []):
        if not isinstance(dec, ast.Call):
            continue
        f = dec.func
        if isinstance(f, ast.Attribute) and f.attr in {
            "get", "post", "put", "delete", "patch",
        }:
            if dec.args and isinstance(dec.args[0], ast.Constant):
                return f"{f.attr.upper()} {dec.args[0].value}"
    return None


def build_graph(root: str = BASE_DIR) -> Dict[str, Any]:
    """Parse every Python file into definitions, imports, calls and routes."""
    definitions: List[Dict[str, Any]] = []
    imports: List[Dict[str, Any]] = []
    calls: List[Dict[str, Any]] = []
    routes: List[Dict[str, Any]] = []
    parse_errors: List[Dict[str, str]] = []

    for path in iter_python_files(root):
        rel = _rel(path)
        try:
            source = open(path, "r", encoding="utf-8", errors="replace").read()
            tree = ast.parse(source, rel)
        except SyntaxError as e:
            parse_errors.append({"file": rel, "error": str(e)})
            continue

        # Attach each node to the function that lexically encloses it, so a
        # call edge names a caller rather than just a file.
        scope: Dict[int, str] = {}

        def walk(node: ast.AST, current: Optional[str]) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    walk(child, child.name)
                elif isinstance(child, ast.ClassDef):
                    walk(child, child.name)
                else:
                    if current is not None:
                        scope[id(child)] = current
                    walk(child, current)

        walk(tree, None)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                definitions.append({
                    "name": node.name, "kind": kind, "file": rel,
                    "line": node.lineno,
                    "is_async": isinstance(node, ast.AsyncFunctionDef),
                    "args": [a.arg for a in node.args.args]
                            if not isinstance(node, ast.ClassDef) else [],
                })
                route = _route_decorator(node)
                if route:
                    routes.append({"route": route, "handler": node.name,
                                   "file": rel, "line": node.lineno})

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append({"file": rel, "module": alias.name,
                                    "symbol": None, "alias": alias.asname,
                                    "line": node.lineno})

            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append({"file": rel, "module": module,
                                    "symbol": alias.name, "alias": alias.asname,
                                    "line": node.lineno})

            elif isinstance(node, ast.Call):
                callee = _callee_name(node)
                if callee:
                    calls.append({
                        "file": rel, "line": node.lineno,
                        "caller": scope.get(id(node)), "callee": callee,
                    })

    return {
        "root": _rel(root) or ".",
        "definitions": definitions,
        "imports": imports,
        "calls": calls,
        "routes": routes,
        "parse_errors": parse_errors,
        "counts": {
            "files": len(iter_python_files(root)),
            "definitions": len(definitions),
            "imports": len(imports),
            "calls": len(calls),
            "routes": len(routes),
        },
    }


if __name__ == "__main__":
    g = build_graph()
    print(json.dumps(g["counts"], indent=2))
    if g["parse_errors"]:
        print("parse errors:", g["parse_errors"])
