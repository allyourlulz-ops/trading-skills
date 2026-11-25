"""Fail if a shipped script imports anything outside the standard library (stdlib-only rule)."""
import ast, pathlib, sys

STD = set(getattr(sys, "stdlib_module_names", ()))  # Python 3.10+


def is_std(top):
    if top in STD or top in sys.builtin_module_names:
        return True
    if STD:
        return False
    # Python 3.9: no stdlib_module_names, so ask where the module lives
    import importlib.util, sysconfig
    try:
        spec = importlib.util.find_spec(top)
    except (ImportError, ValueError):
        return False
    if spec is None:
        return False
    if spec.origin in (None, "built-in", "frozen"):
        return True
    std = pathlib.Path(sysconfig.get_paths()["stdlib"]).resolve()
    o = pathlib.Path(spec.origin).resolve()
    return std in o.parents and "site-packages" not in o.parts


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
            if top not in local and not is_std(top):
                bad.append(f"{p.relative_to(root)}: import {n}")
print("\n".join(bad) or "stdlib only: ok")
sys.exit(1 if bad else 0)
