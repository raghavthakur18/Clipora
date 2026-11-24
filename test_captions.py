#!/usr/bin/env python3
"""Tests of the caption-accuracy logic (transcribe.choose_model / run fallback, app.cap_accuracy) and the Hinglish spelling table.
No audio, no GPU and no download needed. Run: python test_captions.py"""
import sys
from pathlib import Path
sys.argv = ["transcribe.py", "in.m4a", "out.json"]   # transcribe.py reads sys.argv at import
sys.path.insert(0, str(Path(__file__).resolve().parent))
import transcribe as T

def case(name, ok, extra=""):
    print(("PASS  " if ok else "FAIL  ") + name + (f"   [{extra}]" if extra and not ok else ""), flush=True)
    if not ok: print("STOPPED at the first failure."); sys.exit(1)

def pick(acc, device, mb, ready, size=None):
    T.ACC, T.gpu_mb, T.have_model, T.size = acc, (lambda: mb), (lambda n: ready), size
    return T.choose_model(device)

case("1 fast + GPU -> small", pick("fast", "cuda", 8000, True) == "small")
case("2 fast + CPU -> base", pick("fast", "cpu", 0, False) == "base")
case("3 accurate + GPU -> the large model (it will download if missing)", pick("accurate", "cuda", 6144, False) == T.BIG)
case("4 accurate but CPU only -> base, never the large model", pick("accurate", "cpu", 0, True) == "base")
case("5 auto + 6 GB card + model already downloaded -> large", pick("auto", "cuda", 6144, True) == T.BIG)
case("6 auto + 6 GB card + model NOT downloaded -> small (never a silent 1.6 GB download)", pick("auto", "cuda", 6144, False) == "small")
case("7 auto + 4 GB card -> small even if downloaded", pick("auto", "cuda", 4096, True) == "small")
case("8 auto + no NVIDIA card -> small", pick("auto", "cuda", 0, True) == "small")
T.TASK = "translate"; case("9b English captions (translate) -> small, never the large model", pick("accurate", "cuda", 8000, True) == "small"); T.TASK = "transcribe"
case("9 a model named on the command line always wins", pick("fast", "cuda", 8000, True, size="medium") == "medium")

calls = []
class Fake:
    def __init__(self, name, device=None, compute_type=None):
        calls.append((name, compute_type))
        if name == T.BIG: raise RuntimeError("CUDA out of memory")
T.WhisperModel = Fake; T.spoken_language = lambda m: None
class Stop(Exception): pass
def boom(*a, **k): raise Stop()
Fake.transcribe = boom
pick("accurate", "cuda", 6144, True)
try: T.run("cuda", "float16")
except Stop: pass
case("10 the large model fails to start -> falls back to small, the run goes on", [c[0] for c in calls] == [T.BIG, "small"], str(calls))
case("11 the large model is started with the lean memory mode", calls[0][1] == "int8_float16", str(calls))

# long lines from the large model are cut at pauses so the shortlist / caption lines get short lines again
def words_at(start, n, step=0.5, pause_after=()):
    ws, x = [], start
    for i in range(n):
        ws.append(dict(w=f"w{i}", s=round(x, 2), e=round(x + 0.4, 2))); x += step + (1.0 if i in pause_after else 0)
    return ws
ws = words_at(0.0, 60, pause_after=(11, 29, 47)); seg = dict(start=ws[0]["s"], end=ws[-1]["e"], text=" ".join(w["w"] for w in ws), words=ws)
out = T.resplit([seg])
case("16 a 45 s line is cut into several short lines", len(out) >= 4 and max(s["end"] - s["start"] for s in out) <= 10.5, str([(s["start"], s["end"]) for s in out]))
case("17 no word is lost, none repeated, order kept", [w["w"] for s in out for w in s["words"]] == [w["w"] for w in ws])
case("18 the cuts fall on the pauses where there are pauses", {round(s["start"], 1) for s in out} >= {ws[12]["s"], ws[30]["s"], ws[48]["s"]}, str([s["start"] for s in out]))
short = dict(start=0.0, end=3.0, text="hello there", words=words_at(0.0, 2))
case("19 a short line is left exactly as it was", T.resplit([short]) == [short])
nopause = words_at(0.0, 80, step=0.5); seg2 = dict(start=0.0, end=nopause[-1]["e"], text="x", words=nopause)
case("20 speech with no pauses at all is still cut (hard limit), never one 40 s line", max(s["end"] - s["start"] for s in T.resplit([seg2])) <= 10.5)

bad = chr(0xFFFD)
d = T.clean_bad([dict(start=0.0, end=2.0, text="kya baat" + bad + " hai", words=[dict(w="kya", s=0.0, e=0.5), dict(w="baat" + bad, s=0.5, e=1.0), dict(w=bad, s=1.0, e=1.2), dict(w="hai", s=1.2, e=2.0)])])
case("21 a broken-character mark is removed from words and text, and a word that was only that mark disappears", [w["w"] for w in d[0]["words"]] == ["kya", "baat", "hai"] and bad not in d[0]["text"], str(d))

import app
app.env = lambda: {}
case("12 app default accuracy is auto", app.cap_accuracy() == "auto")
app.env = lambda: {"CAPTION_ACCURACY": "accurate"}
case("13 app reads a saved accuracy", app.cap_accuracy() == "accurate")
app.env = lambda: {"CAPTION_ACCURACY": "banana"}
case("14 app ignores a bad saved value", app.cap_accuracy() == "auto")

import hindi_roman as H
for dev, want in [("में", "mein"), ("हम", "hum"), ("पुलिस", "police"), ("गेम", "game"), ("तो", "toh"), ("मैंने", "maine"), ("नहीं", "nahi"), ("क्या बात है", "kya baat hai"), ("राइट गाइज", "right guys"), ("Hello bro", "Hello bro")]:
    case(f"15 spelling: {dev} -> {want}", H.roman(dev) == want, H.roman(dev))
print("ALL PASSED")
