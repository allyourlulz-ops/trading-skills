#!/usr/bin/env python3
"""Golden-fixture runner. Stdlib only. Each case in cases.json runs one script and checks its exit
code and selected JSON fields. Placeholders: {S} scripts dir, {F} fixtures dir, {G} a fresh gate dir
for this run, {nonce:<case>} the nonce an earlier case printed, {OUT} a temp dir holding each case's stdout as <name>.json (later cases may read it).
expect:   {"a.b": value}            exact match on a dotted path (lists indexed by number)
contains: {"a.b": "substring"}      the path (a string or a list of strings) contains the substring
approx:   {"a.b": [value, tol]}     numeric within tol
Exit 0 when every case passes."""
import json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def get(d, path):
    for k in path.split("."):
        d = d[int(k)] if isinstance(d, list) else d[k]
    return d


def run(cases_path, scripts):
    cases = json.load(open(cases_path))
    out_dir, gate = tempfile.mkdtemp(prefix="golden-out-"), tempfile.mkdtemp(prefix="golden-gate-")
    sub = {"{S}": scripts, "{F}": os.path.join(os.path.dirname(cases_path), "fixtures"), "{G}": gate, "{OUT}": out_dir}
    fails = 0
    for c in cases:
        args = [a for a in c["args"]]
        for k, v in sub.items():
            args = [a.replace(k, v) for a in args]
        for i, a_ in enumerate(args):  # {nonce:<case>} = the nonce an earlier case printed
            m = re.fullmatch(r"\{nonce:([\w-]+)\}", a_)
            if m:
                args[i] = json.load(open(os.path.join(out_dir, m.group(1) + ".json"))).get("nonce") or ""
        p = subprocess.run([sys.executable, os.path.join(scripts, c["script"])] + args, capture_output=True, text=True)
        open(os.path.join(out_dir, c["name"] + ".json"), "w").write(p.stdout)
        why = []
        if p.returncode != c["exit"]:
            why.append(f"exit {p.returncode} != {c['exit']}")
        try:
            d = json.loads(p.stdout) if c.get("format", "json") == "json" else {"text": p.stdout}
        except ValueError:
            d = {}; why.append("stdout is not JSON: " + p.stdout[:200] + p.stderr[-300:])
        for k, v in c.get("expect", {}).items():
            try:
                got = get(d, k)
            except (KeyError, IndexError, TypeError):
                got = "<missing>"
            if got != v:
                why.append(f"{k} = {got!r}, expected {v!r}")
        for k, v in c.get("contains", {}).items():
            try:
                got = get(d, k)
            except (KeyError, IndexError, TypeError):
                got = ""
            hay = "\n".join(got) if isinstance(got, list) else str(got)
            if v not in hay:
                why.append(f"{k} does not contain {v!r}: {hay[:200]!r}")
        for k, (v, tol) in c.get("approx", {}).items():
            try:
                got = float(get(d, k))
            except (KeyError, IndexError, TypeError, ValueError):
                got = float("nan")
            if not abs(got - v) <= tol:
                why.append(f"{k} = {got}, expected {v} +/- {tol}")
        fails += bool(why)
        print(("ok    " if not why else "FAIL  ") + c["name"] + ("" if not why else "\n      " + "\n      ".join(why)))
    print(f"{len(cases) - fails}/{len(cases)} golden cases passed")
    return fails


if __name__ == "__main__":
    cp = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "cases.json")
    sd = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "..", "..", "scripts")
    sys.exit(1 if run(cp, os.path.abspath(sd)) else 0)
