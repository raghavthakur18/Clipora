#!/usr/bin/env python3
"""Tests of the auto-switch engine in app.py with fake AI tools (no account, no network, no tokens).
Run: python test_switch.py   -> prints one line per case and ends with ALL PASSED or the first failure.
This file is also the fake tool: it is started as `python test_switch.py --fake <mode>`."""
import json, os, subprocess, sys, tempfile, time
from pathlib import Path

if len(sys.argv) > 2 and sys.argv[1] == "--fake":   # ---- the fake AI tool ----
    mode = sys.argv[2]; sys.stdin.read()
    with open(os.environ["FAKE_LOG"], "a") as f: f.write(mode + "\n")
    if mode == "hang": time.sleep(60)
    if mode == "quota": print("Error: RESOURCE_EXHAUSTED: quota reached", file=sys.stderr); sys.exit(1)
    if mode == "fail": print("something broke", file=sys.stderr); sys.exit(2)
    if mode == "bad": Path(os.environ["FAKE_PF"]).write_text("not json at all"); sys.exit(0)
    if mode == "unicode":   # a tool answer with a non-breaking hyphen, as OpenCode sent: UTF-8 bytes on the pipe
        sys.stdout.buffer.write(("picked " + chr(0x2011) + " two moments " + chr(0x2014) + " done").encode("utf-8") + bytes([10])); sys.stdout.flush()
        Path(os.environ["FAKE_PF"]).write_text(json.dumps([{"start": 1.0, "end": 20.0, "transcript": "clips/src/x.json", "hook": "H", "title": "T"}])); sys.exit(0)
    if mode == "empty": Path(os.environ["FAKE_PF"]).write_text("[]"); sys.exit(0)
    if mode == "nowin": Path(os.environ["FAKE_PF"]).write_text(json.dumps([{"start": 9, "end": 3, "transcript": "x.json"}])); sys.exit(0)
    Path(os.environ["FAKE_PF"]).write_text(json.dumps([{"start": 1.0, "end": 20.0, "transcript": "clips/src/x.json", "hook": "H", "title": "T"}])); sys.exit(0)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app

T = Path(tempfile.mkdtemp(prefix="clipora_switch_test_")); LOG = T / "calls.log"; PF = T / "picks.json"
os.environ["FAKE_LOG"] = str(LOG); os.environ["FAKE_PF"] = str(PF)
app.SWITCH_FILE = T / "switch.json"; app.WS = T
state = dict(modes={}, installed=set(), quota=None, auto=True)
app.installed = lambda t: t in state["installed"]
app.ai_cmd = lambda t, run=False: [sys.executable, str(Path(__file__).resolve()), "--fake", state["modes"].get(t, "ok")]
app.doctor = lambda t: dict(id=t, quota=state["quota"])
app.autoswitch = lambda: state["auto"]
_run = subprocess.run
def fake_run(cmd, *a, **k):   # the shortlist step (nopick --candidates) is not under test
    if len(cmd) > 1 and str(cmd[1]).endswith("nopick.py"): return subprocess.CompletedProcess(cmd, 0)
    return _run(cmd, *a, **k)
app.subprocess.run = fake_run

def reset(modes, installed=("antigravity", "opencode"), quota=None, auto=True):
    state.update(modes=modes, installed=set(installed), quota=quota, auto=auto)
    for f in (LOG, PF, app.SWITCH_FILE, T / "picked_by.txt"): f.unlink(missing_ok=True)
def calls(): return LOG.read_text().split() if LOG.exists() else []
def run(first="antigravity", timeout=20): return app.pick_chain(T, T, 3, PF, first, timeout)
def case(name, ok, extra=""):
    print(("PASS  " if ok else "FAIL  ") + name + (f"   [{extra}]" if extra and not ok else ""), flush=True)
    if not ok: print("STOPPED at the first failure."); sys.exit(1)

reset({}); got = run()
case("1 first tool works -> it is used, the second is never called", got == "antigravity" and calls() == ["ok"] and (T / "picked_by.txt").read_text().strip() == "antigravity", f"{got} {calls()}")

reset({"antigravity": "quota", "opencode": "ok"}); got = run()
case("2 first tool out of quota -> switches to the second", got == "opencode" and calls() == ["quota", "ok"], f"{got} {calls()}")
got = run()
case("3 next run skips the exhausted tool without calling it", got == "opencode" and calls() == ["quota", "ok", "ok"], f"{got} {calls()}")

reset({"antigravity": "quota"}); run(); d = json.loads(app.SWITCH_FILE.read_text())
case("4 the quota pause is stored outside the repo and lasts about an hour", 3500 < d["antigravity"] - time.time() <= 3600, str(d))
d["antigravity"] = time.time() - 5; app.SWITCH_FILE.write_text(json.dumps(d)); state["modes"] = {}; LOG.unlink(missing_ok=True); got = run()
case("5 after the pause ends the tool is tried again", got == "antigravity" and calls() == ["ok"], f"{got} {calls()}")

for m, label in (("bad", "garbage in picks.json"), ("empty", "an empty list"), ("nowin", "a window that ends before it starts"), ("fail", "a crash with no picks")):
    reset({"antigravity": m, "opencode": "ok"}); got = run()
    case(f"6 first tool gives {label} -> switches", got == "opencode" and calls() == [m, "ok"], f"{got} {calls()}")
    case(f"  ...and it is NOT put on pause (only quota errors pause a tool)", not app.SWITCH_FILE.exists())

reset({"antigravity": "hang", "opencode": "ok"}); t0 = time.time(); got = run(timeout=2)
case("7 first tool hangs -> stopped after the time limit, switches", got == "opencode" and time.time() - t0 < 15, f"{got} {time.time() - t0:.1f}s")

reset({"antigravity": "ok", "opencode": "ok"}, installed=("opencode",)); got = run()
case("8 first tool not installed -> skipped, second used", got == "opencode" and calls() == ["ok"], f"{got} {calls()}")

reset({}, installed=()); got = run()
case("9 nothing installed -> None (the caller then picks without AI)", got is None and calls() == [])

reset({"antigravity": "quota", "opencode": "fail"}); got = run()
case("10 every tool fails -> None, no half-written picks left behind", got is None and not PF.exists() and calls() == ["quota", "fail"], f"{got} {calls()}")

reset({"antigravity": "quota", "opencode": "ok"}, auto=False); got = run()
case("11 auto-switch OFF -> only the chosen tool is tried", got is None and calls() == ["quota"], f"{got} {calls()}")

reset({}, quota=[dict(group="Gemini Models", weekly=2.0, **{"5h": 1.0}), dict(group="Claude and GPT models", weekly=1.0, **{"5h": 0.0})]); got = run()
case("12 Antigravity almost out of its limit (<=3%) -> skipped without calling it", got == "opencode" and calls() == ["ok"], f"{got} {calls()}")

reset({}, quota=[dict(group="Gemini Models", weekly=2.0, **{"5h": 1.0}), dict(group="Claude and GPT models", weekly=100.0, **{"5h": 100.0})]); got = run()
case("13 only one group low, the other healthy -> still tried", got == "antigravity" and calls() == ["ok"], f"{got} {calls()}")

reset({"opencode": "ok", "claude": "ok"}, installed=("opencode", "claude")); got = run(first="claude")
case("14 the chosen tool (Claude) goes first, free ones follow", got == "claude" and calls() == ["ok"], f"{got} {calls()}")

reset({"antigravity": "ok"}, installed=("antigravity",)); got = run(first="none")
case("15 chosen = No AI -> no tool is ever called (auto-switch never overrides that choice)", got is None and calls() == [], f"{got} {calls()}")

import io
reset({"antigravity": "unicode", "opencode": "ok"}); real = sys.stdout; sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")   # a Windows console that cannot show U+2011
try: got = run(); err = ""
except Exception as e: got, err = "CRASH", repr(e)
finally: sys.stdout = real
case("16 a tool answers with a character the Windows console cannot print -> no crash, its picks are used", got == "antigravity" and calls() == ["unicode"], f"{got} {err}")

reset({"antigravity": "ok", "opencode": "ok"}); _pw = app.pick_with
def boom(t, *a, **k):
    if t == "antigravity": raise RuntimeError("unexpected")
    return _pw(t, *a, **k)
app.pick_with = boom
try: got = run()
finally: app.pick_with = _pw
case("17 one tool breaks with an unexpected error -> the chain moves on to the next, never crashes", got == "opencode" and calls() == ["ok"], f"{got} {calls()}")

print("ALL PASSED")
