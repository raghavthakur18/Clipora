# Hindi in English letters ("kya baat hai"), for captions. Whisper writes Hindi speech in Devanagari; transcribe.py runs it through here.
# Plain Hinglish spelling, no diacritics. Latin text and punctuation pass through untouched. stdlib only.
import re

CONS = {"क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
        "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n", "प": "p", "फ": "f", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l", "ळ": "l", "व": "v",
        "श": "sh", "ष": "sh", "स": "s", "ह": "h"}
NUKTA = {"क": "q", "ख": "kh", "ग": "g", "ज": "z", "ड": "r", "ढ": "rh", "फ": "f"}  # consonant + the dot below (U+093C)
INDEP = {"अ": "a", "आ": "aa", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u", "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o", "ॲ": "e"}
MATRA = {"ा": "A", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॉ": "o", "ॅ": "e"}
DIGITS = {c: str(i) for i, c in enumerate("०१२३४५६७८९")}
HALANT, NUK, ANUS, CHAND, VISARGA = "्", "़", "ं", "ँ", "ः"
DEV = re.compile(r"[ऀ-ॿ]+")

def _word(w):
    syl = []  # each: [consonants, vowel, nasal, schwa, how many consonants]; schwa = the vowel is the inherent "a" and may be dropped
    i, joined = 0, False
    while i < len(w):
        c = w[i]; i += 1
        if c in CONS:
            r = CONS[c]
            if i < len(w) and w[i] == NUK: r = NUKTA.get(c, r); i += 1
            if joined and syl: syl[-1][0] += r; syl[-1][4] += 1
            else: syl.append([r, "a", "", True, 1])
            joined = False
        elif c == HALANT: joined = True  # the next consonant joins this one (k + sh = ksh)
        elif c in MATRA and syl: syl[-1][1], syl[-1][3] = MATRA[c], False
        elif c in INDEP: syl.append(["", INDEP[c], "", False, 0]); joined = False
        elif c in (ANUS, CHAND) and syl: syl[-1][2] = "n"
        elif c == VISARGA and syl: syl[-1][2] = "h"
        elif c == NUK: pass
        else: syl.append([DIGITS.get(c, c), "", "", False, 0]); joined = False
    if joined and syl: syl[-1][3], syl[-1][1] = False, ""  # word ends in a halant: no vowel
    # Hindi drops the inherent "a" at the end of a word and in V C a C V ("samajh", "karta"), but keeps it before a joined pair ("namaste"). Right to left, so each choice sees the outcome to its right.
    if len(syl) > 1 and syl[-1][3]: syl[-1][1] = ""
    for k in range(len(syl) - 2, 0, -1):
        if syl[k][3] and syl[k - 1][1] and syl[k + 1][1] and syl[k + 1][4] < 2: syl[k][1] = ""
    r = "".join(s[0] + (s[1].replace("A", "a" if k == len(syl) - 1 else "aa")) + s[2] for k, s in enumerate(syl))  # the long a: "baat" inside a word, "kya" at its end
    return r.replace("jny", "gy").replace("jn", "gy")  # ज्ञ

# Whole words people write one fixed way in Hinglish, where the letter rules above would give a stiff spelling ("men", "ham", "pulis"). Anything not listed goes through the rules.
WORDS = dict([
    ("में", "mein"), ("मे", "mein"), ("मैं", "main"), ("मैंने", "maine"), ("हमें", "hamein"), ("हम", "hum"), ("हमारे", "hamare"), ("हमारा", "hamara"), ("हमारी", "hamari"),
    ("यह", "yeh"), ("ये", "ye"), ("वो", "woh"), ("वह", "woh"), ("तो", "toh"), ("नहीं", "nahi"), ("नही", "nahi"), ("क्यों", "kyun"), ("कहाँ", "kahan"), ("कहां", "kahan"),
    ("पुलिस", "police"), ("पुलिसने", "police ne"), ("गेम", "game"), ("गेमिंग", "gaming"), ("सुपर", "super"), ("कार", "car"), ("कारें", "cars"), ("कार्स", "cars"), ("कार्ष", "cars"),
    ("वीडियो", "video"), ("लाइव", "live"), ("स्ट्रीम", "stream"), ("चैट", "chat"), ("प्लेयर", "player"), ("मिशन", "mission"), ("लेवल", "level"), ("सिक्स", "six"),
    ("गाड़ी", "gaadi"), ("गाड़ियाँ", "gaadiyan"), ("गाड़ियां", "gaadiyan"), ("गाडी", "gaadi"), ("भाई", "bhai"), ("यार", "yaar"), ("ठीक", "theek"), ("अच्छा", "accha"), ("पैसे", "paise"), ("पैसा", "paisa"),
    ("राइट", "right"), ("गाइज", "guys"), ("गाइस", "guys"), ("आइलेंड", "island"), ("साइकल", "cycle"), ("एंड", "and"), ("ऑल", "all"), ("ओके", "okay"), ("सूपर", "super"), ("बाइक", "bike"), ("हेलीकॉप्टर", "helicopter"),
])

def roman(text):
    """Devanagari -> English letters. Text with no Devanagari comes back unchanged."""
    if not DEV.search(text or ""): return text
    return DEV.sub(lambda m: WORDS.get(m.group()) or _word(m.group()), text.replace("।", ".").replace("॥", "."))

if __name__ == "__main__":
    import sys; sys.stdout.reconfigure(encoding="utf-8")  # a Windows console cannot print Devanagari otherwise
    bad = 0
    for a, b in [("क्या बात है", "kya baat hai"), ("काम", "kaam"), ("समझ", "samajh"), ("करता", "karta"), ("कमल", "kamal"), ("बदलना", "badalna"), ("आप", "aap"), ("मुझे", "mujhe"),
                 ("कुछ", "kuchh"), ("ज्ञान", "gyaan"), ("हैं", "hain"), ("लेटस गो", "letas go"), ("Hello bro", "Hello bro"), ("नमस्ते", "namaste"), ("फिर", "fir"), ("जल्दी", "jaldi"),
                 ("वो चाथ करते है एक गेम को.", "woh chaath karte hai ek game ko."), ("१२ बजे।", "12 baje."), ("मैंने यह कहा", "maine yeh kaha"), ("हम गेम में पुलिस से बचे", "hum game mein police se bache"), ("तो आज हमें सुपर कार्स चुरानी हैं", "toh aaj hamein super cars churaani hain"), ("नहीं यार", "nahi yaar")]:
        got = roman(a); bad += got != b; print("ok  " if got == b else "DIFF", a, "->", got, "(want", b + ")")
    assert not bad, f"{bad} romanizer checks failed"
