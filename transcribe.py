# Free local transcript with word timings (faster-whisper on GPU if present, else CPU), plus loud moments.
# Usage: python transcribe.py in.m4a out.json [model]     (model default: small on GPU, base on CPU)
import glob, json, os, subprocess, sys, time
import numpy as np
for d in glob.glob(os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "*", "bin")) if os.name == "nt" else []:  # pip CUDA libs (cublas, cudnn) -> GPU
    os.add_dll_directory(d); os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
from faster_whisper import WhisperModel
size = sys.argv[3] if len(sys.argv) > 3 else None
# names Whisper should know; it also makes Whisper punctuate, which the sentence snapping and caption lines need (Speed test: no full stops -> full sentences)
TASK = "translate" if os.environ.get("TRANSCRIBE_TASK") == "translate" else "transcribe"  # transcribe = captions in the spoken language (Hindi comes out in English letters); translate = English captions from any speech, off by default
VOCAB = os.environ.get("TRANSCRIBE_PROMPT", "GTA 6, Grand Theft Auto VI, GTA 5, San Andreas, Vice City, Leonida, Lucia, Jason, Rockstar, PS5, Xbox, Kai Cenat, IShowSpeed. Chat, KEKW, LUL, W, bro.")  # streamers say "chat" all the time: without it Whisper writes "Chad"

def spoken_language(model, secs=240):
    """The language of the first few minutes (voice only, silence skipped), so the English word list is used only for English."""
    p = subprocess.run(["ffmpeg", "-v", "error", "-t", str(secs), "-i", sys.argv[1], "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"], capture_output=True)
    a = np.frombuffer(p.stdout, np.int16).astype(np.float32) / 32768
    if len(a) < 16000: return None
    try: return model.detect_language(a, vad_filter=True, language_detection_segments=4)[0]
    except Exception: return None  # detection is a courtesy: Whisper still finds the language itself

# Caption accuracy (Settings): fast = the small model; accurate = the large one (better Hindi, needs an NVIDIA card, ~1.6 GB download on first use);
# auto (default) = the large one only when the card has the memory AND it is already downloaded: it never starts a big download by itself.
ACC = os.environ.get("TRANSCRIBE_ACCURACY", "auto")
BIG, BIG_MIN_MB = "large-v3-turbo", 6000
def gpu_mb():
    try: return int(subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout.split()[0])
    except Exception: return 0  # no NVIDIA card / no driver
def have_model(name):
    try:
        from faster_whisper.utils import download_model
        download_model(name, local_files_only=True); return True
    except Exception: return False
def choose_model(device):
    small = "small" if device == "cuda" else "base"  # base on CPU: ~3x faster, fine for English
    if size: return size
    if device != "cuda" or ACC == "fast" or TASK == "translate": return small  # translate (English captions): the large turbo model is not trained for it and answered in Hindi script in the 24 Nov test
    if ACC == "accurate": return BIG
    return BIG if gpu_mb() >= BIG_MIN_MB and have_model(BIG) else small

def run(device, ct):
    name = choose_model(device); small = "small" if device == "cuda" else "base"
    try: model = WhisperModel(name, device=device, compute_type="int8_float16" if name == BIG else ct)
    except Exception as e:
        if name != BIG: raise
        print("accurate caption model could not start (", str(e)[:80], ") -> fast model", flush=True); name = small; model = WhisperModel(name, device=device, compute_type=ct)
    print("caption model:", name, flush=True)
    lang = spoken_language(model)
    prompt = VOCAB if lang == "en" or TASK == "translate" else None  # the English word list throws Whisper off on other languages (Hindi came out as junk symbols)
    segs, info = model.transcribe(sys.argv[1], word_timestamps=True, vad_filter=True, initial_prompt=prompt, task=TASK, language=lang)
    prog = os.path.splitext(sys.argv[2])[0] + ".progress"  # the app reads this for the real "minutes done / time left": audio seconds done, total, when decoding began
    t0, last, got = time.time(), 0.0, []
    for s in segs:  # pulling the segments here forces the work now, so a missing GPU library fails here, not later
        got.append(s)
        if time.time() - last >= 3:
            last = time.time()
            try: open(prog + ".tmp", "w").write(json.dumps(dict(done=round(s.end, 1), total=round(info.duration, 1), t0=t0, t=last))); os.replace(prog + ".tmp", prog)
            except OSError: pass  # progress is a courtesy, never a reason to fail the transcript
    return got, info

def loudness(path, sr=4000):
    """dB per second of the whole audio, streamed from ffmpeg in chunks (a 6-hour stream stays small in memory)."""
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"], stdout=subprocess.PIPE)
    db = []
    while chunk := p.stdout.read(sr * 2 * 60):
        x = np.frombuffer(chunk[: len(chunk) // (sr * 2) * sr * 2], np.int16).astype(np.float32).reshape(-1, sr)
        db += list(10 * np.log10((x ** 2).mean(1) + 1))
    p.wait(); return np.array(db)

def loud_tags(segments, db):
    """Mark segments whose loudest second is far above this video's normal level: screams, crashes, hype. Claude reads these."""
    if len(db) < 30: return {}
    base, top = np.median(db), np.percentile(db, 97)
    peaks = {i: db[int(s["start"]):int(s["end"]) + 1].max(initial=0) for i, s in enumerate(segments)}
    # jump over the 20 s before: a scream after calm talk counts even in a stream that is loud all the time (hype reactors, trailer audio)
    jump = {i: peaks[i] - np.median(db[max(int(s["start"]) - 20, 0):max(int(s["start"]), 1)]) for i, s in enumerate(segments)}
    lift = {i: max(peaks[i] - base, jump[i]) for i in peaks}
    hot = sorted((i for i in peaks if (peaks[i] >= top and peaks[i] - base >= 6) or jump[i] >= 9), key=lambda i: -lift[i])[:max(3, len(segments) // 20)]  # loudest 5% at most
    return {i: f" [LOUD +{lift[i]:.0f}dB]" for i in hot}

def clean_bad(data):
    """Whisper sometimes ends a word on half a character (U+FFFD): it would show as an empty box in a caption."""
    bad = chr(0xFFFD)
    for sg in data:
        sg["words"] = [w for w in (dict(x, w=x["w"].replace(bad, "").strip()) for x in sg["words"]) if w["w"]]; sg["text"] = sg["text"].replace(bad, "").strip()
    return data
def _line(ws):
    text = " ".join(w["w"] for w in ws)
    return dict(start=ws[0]["s"], end=ws[-1]["e"], text=text[:1].upper() + text[1:], words=ws)
def resplit(data, soft=6.0, hard=10.0, pause=0.45):
    """The large model writes very long lines (up to 30 s of speech in one). The moment shortlist, the sentence snapping and the caption lines are built for short lines like the small model's (about 2 s), and found NO candidate moment on long ones (24 Nov test). So each long line is cut at the pauses between words; short lines are left alone."""
    out = []
    for sg in data:
        ws = sg["words"]
        if sg["end"] - sg["start"] <= soft or len(ws) < 2: out.append(sg); continue
        cur = [ws[0]]
        for w in ws[1:]:
            dur, gap = w["e"] - cur[0]["s"], w["s"] - cur[-1]["e"]
            if (gap >= pause and dur >= 2.0) or (dur >= soft and gap >= 0.15) or dur >= hard: out.append(_line(cur)); cur = [w]
            else: cur.append(w)
        out.append(_line(cur))
    return out

if __name__ == "__main__":
    src, out = sys.argv[1], sys.argv[2]
    try:
        if sys.platform == "darwin": raise RuntimeError("no CUDA on macOS")
        segs, info = run("cuda", "float16")
    except Exception as e: print("GPU not usable (", str(e)[:60], ") -> CPU"); segs, info = run("cpu", "int8")
    data = [dict(start=round(s.start, 2), end=round(s.end, 2), text=s.text.strip(),
                 words=[dict(w=w.word.strip(), s=round(w.start, 2), e=round(w.end, 2)) for w in s.words]) for s in segs]
    if info.language == "hi" and TASK == "transcribe":  # Whisper writes Hindi in Devanagari; captions get English letters ("kya baat hai")
        from hindi_roman import roman
        for sg in data:
            sg["text"] = roman(sg["text"]); sg["text"] = sg["text"][:1].upper() + sg["text"][1:]
            for w in sg["words"]: w["w"] = roman(w["w"])
    data = resplit(clean_bad(data))
    tags = loud_tags(data, loudness(src))
    off = float(os.environ.get("TRANSCRIBE_OFFSET", 0))  # audio was a window of a long VOD: shift to full-VOD times
    for sg in data: sg["start"] = round(sg["start"] + off, 2); sg["end"] = round(sg["end"] + off, 2); [w.update(s=round(w["s"] + off, 2), e=round(w["e"] + off, 2)) for w in sg["words"]]
    json.dump(dict(lang=info.language, segments=data), open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # compact timeline for the AI to read: one line per segment, loud moments marked
    open(out.replace(".json", ".txt"), "w", encoding="utf-8").write("\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}{tags.get(i, '')}" for i, s in enumerate(data)))
    try: os.remove(os.path.splitext(out)[0] + ".progress")
    except OSError: pass
    print("ok", len(data), "segments,", info.language, ",", len(tags), "loud moments")
