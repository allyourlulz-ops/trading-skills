"""Fail if a shipped script imports anything outside the standard library (stdlib-only rule)."""
import ast, pathlib, sys

STD = set(getattr(sys, "stdlib_module_names", ())) or {
    "argparse", "ast", "csv", "datetime", "decimal", "filecmp", "hashlib", "hmac", "json", "math", "os", "random",
    "re", "secrets", "statistics", "subprocess", "sys", "tempfile", "time", "typing", "zoneinfo", "itertools",
    "collections", "functools", "bisect", "heapq", "pathlib", "shutil", "string", "textwrap", "urllib", "io",
    "uuid", "copy", "glob", "fnmatch", "py_compile", "__future__", "dataclasses", "enum", "operator", "contextlib"}
root = pathlib.Path(__file__).resolve().parent.parent / "skills"
local = {p.stem for p in root.rglob("scripts/*.py")} | {"run_golden"}
bad = []
for p in sorted(root.rglob("*.py")):
    if "assets" in p.parts:  # templates for the user's own engine, not shipped tooling
        continue
    for node in ast.walk(ast.parse(p.read_text())):
        names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
            [node.module] if isinstance(node, ast.ImportFrom) and node.module and node.level == 0 else [])
        for n in names:
            top = n.split(".")[0]
            if top not in STD and top not in local:
                bad.append(f"{p.relative_to(root)}: import {n}")
print("\n".join(bad) or "stdlib only: ok")
sys.exit(1 if bad else 0)
