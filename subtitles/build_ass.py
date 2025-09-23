#!/usr/bin/env python3
import pathlib, json, math, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
HEADER = ROOT / "subtitles" / "ass_header.ass"
STORY = ROOT / "story" / "story.txt"
DUR_JSON = ROOT / "audio" / "duration.json"
OUT = ROOT / "subtitles" / "captions.ass"

if not HEADER.exists():
    print("ass_header.ass manquant", file=sys.stderr); sys.exit(1)
if not STORY.exists():
    print("story.txt manquant", file=sys.stderr); sys.exit(1)
if not DUR_JSON.exists():
    print("duration.json manquant", file=sys.stderr); sys.exit(1)

story = STORY.read_text(encoding="utf-8").strip()
if not story:
    print("story vide", file=sys.stderr); sys.exit(1)

dur = float(json.loads(DUR_JSON.read_text(encoding="utf-8")).get("seconds", 0.0))
if dur <= 0.1:
    print("durée audio invalide", file=sys.stderr); sys.exit(1)

# Split en mots
words = re.findall(r"\S+", story)
n = len(words)
if n == 0:
    print("aucun mot", file=sys.stderr); sys.exit(1)

# Nombre de lignes ~ dur / 3s (entre 2.5 et 3.5)
lines_count = max(1, round(dur / 3.0))
w_per_line = max(1, math.ceil(n / lines_count))

# Chunk words -> lines
chunks = []
for i in range(0, n, w_per_line):
    chunks.append(words[i:i+w_per_line])

# Helper time -> h:MM:SS.cs
def tcode(ts: float) -> str:
    if ts < 0: ts = 0
    h = int(ts // 3600)
    m = int((ts % 3600) // 60)
    s = int(ts % 60)
    cs = int(round((ts - int(ts)) * 100))
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

# Écriture
hdr = HEADER.read_text(encoding="utf-8")
with OUT.open("w", encoding="utf-8") as f:
    f.write(hdr)
    f.write("\n")
    f.write("[Events]\n")
    f.write("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")

    # Répartition des durées proportionnelle au nombre de mots
    total_words = sum(len(c) for c in chunks)
    t = 0.0
    for c in chunks:
        share = len(c) / total_words
        seg = max(2.0, dur * share)  # au moins 2s
        start = t
        end = min(t + seg, dur)
        # Karaoke tags (\k en centisecondes)
        per_word = (end - start) / max(1, len(c))
        centi = max(1, int(round(per_word * 100)))
        safe_tokens = []
        for w in c:
            wt = w.replace("{", "(").replace("}", ")")
            safe_tokens.append(r"{\k" + str(centi) + "}" + wt)
        line_text = " ".join(safe_tokens)
        f.write(f"Dialogue: 0,{tcode(start)},{tcode(end)},TikTok,,0,0,80,,{line_text}\n")
        t = end

print(f"ASS written to {OUT}")