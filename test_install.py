#!/usr/bin/env python3
"""Tests of the Install button engine in app.py with harmless fake commands (nothing is installed).
Run: python test_install.py  -> one line per case, ends with ALL PASSED or the first failure."""
import json, shutil, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import app

PY = sys.executable
def case(name, ok, extra=""):
    print(("PASS  " if ok else "FAIL  ") + name + (f"   [{extra}]" if extra and not ok else ""), flush=True)
    if not ok: print("STOPPED at the first failure."); sys.exit(1)
def wait(jid, secs=30):
    t = time.time()
    while app.JOBS[jid]["status"] == "running" and time.time() - t < secs: time.sleep(0.1)
    return app.JOBS[jid]
def plan(steps): app.SETUP = {"fake": {"install": {app.OSKEY: steps}}}; app.PROV["fake"] = dict(label="Fake tool", bin="fake_zzz", tools=True, text=None, run=None, note="")
app.installed = lambda i: False
_which = shutil.which
app.shutil.which = lambda n, *a, **k: PY if n in ("fakecmd", "winget") else _which(n, *a, **k)   # the fake program name resolves to python

ok = lambda code: dict(label="ok step", cmd=["fakecmd", "-c", f"print('hello'); raise SystemExit({code})"])

for bad in ("nope_tool", None, 5):
    try: app.start_install(bad); case("1 unknown tool id is refused", False)
    except ValueError: pass
case("1 unknown tool id is refused", True)
app.SETUP = {};
try: app.start_install("claude"); case("2 a tool with no checked install plan is refused", False)
except ValueError: case("2 a tool with no checked install plan is refused", True)

plan([ok(0), dict(label="second", cmd=["fakecmd", "-c", "print('two')"])]); j = wait(app.start_install("fake"))
case("3 two steps run in order, job ends 'done'", j["status"] == "done" and [l for l in j["log"] if l.startswith("step:")] == ["step: ok step", "step: second"] and "hello" in j["log"] and "two" in j["log"], str(j["log"]))
case("4 after the steps it reports whether the tool can now be found", any(l.startswith("check:") for l in j["log"]), str(j["log"]))

plan([ok(3), dict(label="never runs", cmd=["fakecmd", "-c", "print('SHOULD-NOT-RUN')"])]); j = wait(app.start_install("fake"))
case("5 a failing step stops the install, later steps never run", j["status"] == "failed" and "SHOULD-NOT-RUN" not in j["log"] and any("exit code 3" in l for l in j["log"]), str(j["log"]))

plan([dict(label="Skipped", cmd=["fakecmd", "-c", "print('SKIPPED-RAN')"], skip_if_found="python"), dict(label="Runs", cmd=["fakecmd", "-c", "print('ran')"], skip_if_found="no_such_program_zzz")]); j = wait(app.start_install("fake"))
case("6 a step is skipped when its program is already there, and runs when it is not", "SKIPPED-RAN" not in j["log"] and "ran" in j["log"] and any(l.startswith("skip:") for l in j["log"]), str(j["log"]))

plan([dict(label="Needs a missing program", cmd=["no_such_program_zzz", "x"])]); j = wait(app.start_install("fake"))
case("7 a missing program fails with a plain message, nothing else runs", j["status"] == "failed" and any("was not found" in l for l in j["log"]), str(j["log"]))

plan([dict(label="winget already installed", cmd=["winget", "-c", "import os; os._exit(-1978335189)"])]); j = wait(app.start_install("fake"))   # Windows hands the real exit code 0x8A15002B back as an unsigned number
case("8 winget's 'already installed' exit code counts as success", j["status"] == "done", str(j["log"]))
case("8b ...in both its signed and unsigned forms", 0x8A15002B in app.WINGET_OK and 0x8A15002B - 2 ** 32 in app.WINGET_OK)
plan([dict(label="other launcher, same code", cmd=["fakecmd", "-c", "import os; os._exit(-1978335189)"])]); j = wait(app.start_install("fake"))
case("8c ...but only for winget: any other program with that code is a failure", j["status"] == "failed", str(j["log"]))

plan([dict(label="slow", cmd=["fakecmd", "-c", "import time; time.sleep(3)"])]); first = app.start_install("fake")
try: app.start_install("fake"); case("9 a second install while one runs is refused", False)
except ValueError as e: case("9 a second install while one runs is refused", "already running" in str(e))
wait(first)

app.INSTALL_STEP_SECS = 1; plan([dict(label="stalls", cmd=["fakecmd", "-c", "import time; time.sleep(20)"]), dict(label="never", cmd=["fakecmd", "-c", "print('NEVER-RAN')"])]); t0 = time.time(); j = wait(app.start_install("fake"))
case("9b a stalled step is stopped after the time limit, later steps never run", j["status"] == "failed" and any("stopped" in l for l in j["log"]) and "NEVER-RAN" not in j["log"] and time.time() - t0 < 10, str(j["log"]))
app.INSTALL_STEP_SECS = 1200
plan([dict(label="portable", cmd=["fakecmd", "-c", "print('Unable to remove Portable package as it has been modified; to override this check use --force'); raise SystemExit(5)"])]); j = wait(app.start_install("fake"))
case("9c winget's 'package has been modified' failure gets a plain-words hint", j["status"] == "failed" and any(l.startswith("hint:") for l in j["log"]), str(j["log"]))

plan([ok(0)]); app.OSKEY = "plan9"
try: app.start_install("fake"); case("10 a system with no checked commands gets no install button", False)
except ValueError: case("10 a system with no checked commands gets no install button", True)
app.OSKEY = "windows"

plan([ok(0)]); app.PROV["antigravity"] = app.PROV.get("antigravity", dict(label="x", bin="agy", tools=True, text=None, run=None, note=""))
app.SETUP = {"antigravity": {"site": "s", "windows": [{"text": "a"}], "install": {"windows": [dict(label="L", cmd=["winget", "install", "-e", "--id", "X"])]}}}
info = app.setup_info("antigravity")
case("11 the page is told the exact commands it will ask the user to confirm", info["install"] == [dict(label="L", cmd="winget install -e --id X", skip=False)], str(info))

# the shipped file: fixed lists only, no shell tricks, only the two known launchers
app.SETUP = {k: v for k, v in json.loads((Path(app.HERE) / "ai_setup.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}
bad = []
for tool, e in app.SETUP.items():
    for system, steps in (e.get("install") or {}).items():
        if system not in e.get("verified", []): bad.append(f"{tool}/{system}: install offered but not marked checked")
        for s in steps:
            c = s["cmd"]
            if not isinstance(c, list) or not all(isinstance(x, str) for x in c): bad.append(f"{tool}: cmd is not a list of strings")
            elif c[0] not in ("winget", "npm"): bad.append(f"{tool}: unexpected launcher {c[0]}")
            elif any(ch in x for x in c for ch in "&;|<>`$") : bad.append(f"{tool}: shell character in {c}")
case("12 ai_setup.json: every install is a fixed list, a known launcher, no shell characters, and only for systems marked checked", not bad, str(bad))
print("ALL PASSED")
