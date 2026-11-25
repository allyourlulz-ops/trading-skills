#!/usr/bin/env python3
"""Offline checks for trading-execution: scripts compile and answer --help, and the shared risk
scripts match trading-research's copies byte for byte when both skills sit in one repo."""
import filecmp, os, py_compile, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__)); SCRIPTS = os.path.join(HERE, "..", "scripts")
TMP = tempfile.mkdtemp(); fails = []
for f in sorted(os.listdir(SCRIPTS)):
    if f.endswith(".py"):
        try:
            py_compile.compile(os.path.join(SCRIPTS, f), cfile=os.path.join(TMP, f + "c"), doraise=True); ok = True
        except py_compile.PyCompileError:
            ok = False
        code = subprocess.run([sys.executable, f, "--help"], cwd=SCRIPTS, capture_output=True).returncode
        for name, cond in ((f"compile {f}", ok), (f"help {f}", code == 0)):
            print(("PASS " if cond else "FAIL ") + name); fails += [] if cond else [name]
other = os.path.join(HERE, "..", "..", "trading-research", "scripts")
if os.path.isdir(other):
    for f in ("risk_check.py", "position_size.py"):
        same = filecmp.cmp(os.path.join(SCRIPTS, f), os.path.join(other, f), shallow=False)
        print(("PASS " if same else "FAIL ") + f"{f} matches trading-research"); fails += [] if same else [f]
print(f"\n{len(fails)} failed" if fails else "\nall passed"); sys.exit(1 if fails else 0)
