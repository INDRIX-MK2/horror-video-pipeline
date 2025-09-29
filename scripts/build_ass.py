#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, argparse, pathlib, subprocess, re

ap = argparse.ArgumentParser()
ap.add_argument("--transcript", required=True)
ap.add_argument("--audio", required=True)
ap.add_argument("--out", default="subs/captions.ass")
ap.add_argument("--font", default="Arial")
ap.add_argument("--size", type=int, default=70)
ap.add_argument("--align", type=int, default=5)
ap.add_argument("--margin-v", type=int, default=200)
ap.add_argument("--words-per-line", type=int, default=4)
ap.add_argument("--max-lines", type=int, default=4)
ap.add_argument("--min-chunk", type=float, default=1.0)

# >>> Anti-dérive (nouveaux paramètres)
ap.add_argument("--lead", type=float, default=-0, help="avance globale (s, négatif = plus tôt)")
ap.add_argument("--speed", type=float, default=1.0, help="facteur de compression de durée (1.0 = inchangé)")
# <<<

ap.add_argument("--primary-colour", default="&H0080FFF3")
ap.add_argument("--outline-colour", default="&H00000000")
ap.add_argument("--back-colour", default="&H64000000")
ap.add_argument("--outline", type=int, default=3)
ap.add_argument("--shadow", type=int, default=2)
args = ap.parse_args()

tpath = pathlib.Path(args.transcript)
apath = pathlib.Path(args.audio)
opath = pathlib.Path(args.out)
opath.parent.mkdir(parents=True, exist_ok=True)

if not tpath.exists() or not tpath.stat().st_size:
    print("Transcript introuvable/vide", file=sys.stderr); sys.exit(1)
if not apath.exists() or not apath.stat().st_size:
    print("Audio introuvable/vide", file=sys.stderr); sys.exit(1)

def ffprobe_duration(p: pathlib.Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error",
            "-show_entries","format=duration",
            "-of","default=nk=1:nw=1", str(p)
        ]).decode("utf-8","ignore").strip()
        return max(0.01, float(out))
    except Exception:
        return 0.01

def to_ass_ts(sec: float) -> str:
    if sec < 0: sec = 0
    h = int(sec // 3600); m = int((sec % 3600) // 60); s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    if cs >= 100:
        s += 1; cs -= 100
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

RE_STAGE = re.compile(
    r"^\s*(?:\[(?:[^\]]+)\]|\((?:[^)]+)\)|(?:intro|hook|scène|scene|narrateur|voix\s*\d+)\s*:)\s*",
    flags=re.IGNORECASE,
)

def clean_text(s: str) -> str:
    s = RE_STAGE.sub("", s.strip())
    s = re.sub(r"\[[^\]]+\]", "", s)
    s = re.sub(r"\([^)]+\)", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def split_sentences(text: str):
    parts = re.split(r"([\.!?…]+)", text)
    out = []
    for i in range(0, len(parts), 2):
        chunk = parts[i].strip()
        sep = parts[i+1] if i+1 < len(parts) else ""
        buf = (chunk + sep).strip()
        if buf:
            out.append(buf)
    if not out:
        out = [text.strip()]
    return out

def ass_escape(s: str) -> str:
    s = s.replace("\\", r"\\")
    s = s.replace("{", r"\{").replace("}", r"\}")
    return s

def wrap_to_lines(words, max_lines=3, words_per_line=4):
    if max_lines < 1: max_lines = 1
    chunks, buf = [], []
    for w in words:
        buf.append(w)
        if len(buf) >= words_per_line:
            chunks.append(" ".join(buf)); buf=[]
    if buf:
        chunks.append(" ".join(buf))
    if not chunks:
        return [""]
    while len(chunks) > max_lines:
        lengths = [len(c.split()) for c in chunks]
        i = lengths.index(min(lengths))
        if i < len(chunks)-1:
            chunks[i] = chunks[i] + " " + chunks[i+1]
            del chunks[i+1]
        else:
            chunks[i-1] = chunks[i-1] + " " + chunks[i]
            del chunks[i]
    return chunks

# ----------------------------
# Lecture + découpe
# ----------------------------
raw = tpath.read_text(encoding="utf-8", errors="ignore")
lines = [clean_text(ln) for ln in raw.splitlines() if clean_text(ln)]
full_text = " ".join(lines).strip()
sentences = split_sentences(full_text)

items = []
total_words = 0
for sent in sentences:
    w = sent.split()
    if not w: continue
    total_words += len(w)
    wrapped = wrap_to_lines(w, max_lines=args.max_lines, words_per_line=args.words_per_line)
    items.append((w, wrapped))

if not items:
    print("Aucune phrase après nettoyage.", file=sys.stderr); sys.exit(1)

audio_dur = ffprobe_duration(apath)

# ----------------------------
# Durées “brutes” proportionnelles
# ----------------------------
events = []
t = 0.0
for w, wrapped in items:
    share = (len(w) / total_words) * audio_dur
    dur = max(args.min_chunk, share)
    s = t
    e = min(audio_dur, s + dur)
    t = e
    # Prépare le texte (chaque ligne échappée, séparateur \N non échappé)
    escaped_lines = [ass_escape(line.strip()) for line in wrapped if line.strip()]
    text = r"\N".join(escaped_lines)
    events.append([s, e, text])

if events and events[-1][1] > audio_dur:
    events[-1][1] = audio_dur

# ----------------------------
# Anti-dérive : avance + compression
# Recalage autour du centre de chaque sous-titre.
# ----------------------------
lead = float(args.lead)
speed = float(args.speed)
MIN_GAP = 0.02  # 20 ms pour éviter chevauchement

adj = []
prev_end = 0.0
for s, e, txt in events:
    dur = max(0.01, e - s)
    mid = (s + e) / 2.0
    new_dur = max(args.min_chunk, dur * speed)
    ns = mid - new_dur / 2.0 + lead
    ne = ns + new_dur

    # Empêcher chevauchements et bornes
    if ns < prev_end + MIN_GAP:
        ns = prev_end + MIN_GAP
        ne = ns + new_dur
    if ne > audio_dur:
        ne = audio_dur
        ns = max(prev_end + MIN_GAP, ne - new_dur)
    adj.append([ns, ne, txt])
    prev_end = ne

# ----------------------------
# Écriture ASS
# ----------------------------
hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTok,{args.font},{args.size},{args.primary_colour},&H00000000,{args.outline_colour},{args.back_colour},0,0,0,0,100,100,0,0,1,{args.outline},{args.shadow},{args.align},40,40,{args.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".replace("\r\n","\n")

with opath.open("w", encoding="utf-8") as f:
    f.write(hdr)
    for s, e, txt in adj:
        f.write(f"Dialogue: 0,{to_ass_ts(s)},{to_ass_ts(e)},TikTok,,0,0,0,,{txt}\n")

print(f"[build_ass] écrit: {opath} (durée audio détectée: {audio_dur:.2f}s)")
print(f"Anti-derivage appliqué: lead={lead:+.2f}s, speed={speed:.3f}")