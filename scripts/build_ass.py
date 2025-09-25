#!/usr/bin/env python3
import sys, argparse, pathlib, subprocess, re

ap = argparse.ArgumentParser()
ap.add_argument("--transcript", required=True)
ap.add_argument("--audio", required=True)
ap.add_argument("--out", default="subs/captions.ass")
ap.add_argument("--font", default="Arial")
ap.add_argument("--size", type=int, default=60)   # tu pourras changer à la volée
args = ap.parse_args()

tpath = pathlib.Path(args.transcript)
apath = pathlib.Path(args.audio)
opath = pathlib.Path(args.out)
opath.parent.mkdir(parents=True, exist_ok=True)

if not tpath.exists() or not tpath.stat().st_size:
    print("Transcript introuvable/vide", file=sys.stderr); sys.exit(1)
if not apath.exists() or not apath.stat().st_size:
    print("Audio introuvable/vide", file=sys.stderr); sys.exit(1)

def dur_audio(p):
    out = subprocess.check_output([
        "ffprobe","-v","error","-show_entries","format=duration",
        "-of","default=nk=1:nw=1", str(p)
    ]).decode("utf-8","ignore").strip()
    try: return float(out)
    except: return 0.0

def to_ass_ts(sec):
    if sec < 0: sec = 0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

audio_dur = max(0.01, dur_audio(apath))
raw = tpath.read_text(encoding="utf-8")
# Nettoyage très léger
raw = re.sub(r"\[[^\]]+\]", "", raw)
raw = re.sub(r"\([^)]+\)", "", raw)
lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]

# S'il n'y a qu'une ligne, on la coupe tous les ~7 mots pour l’écran
words = []
for ln in lines:
    words.extend(ln.split())

chunks = []
buf = []
for i,w in enumerate(words, start=1):
    buf.append(w)
    if len(buf) >= 7:          # 7 mots par ligne (approx)
        chunks.append(" ".join(buf)); buf=[]
if buf:
    chunks.append(" ".join(buf))

n = max(1, len(chunks))
# Répartition *équitable* du temps total
per = audio_dur / n
events = []
t = 0.0
for text in chunks:
    s = t
    e = min(audio_dur, t + per)
    events.append((s,e,text))
    t = e

# Header ASS minimal
hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTok,{args.font},{args.size},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,3,0,2,40,40,200,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".replace("\r\n","\n")

with opath.open("w", encoding="utf-8") as f:
    f.write(hdr)
    for s,e,txt in events:
        f.write(f"Dialogue: 0,{to_ass_ts(s)},{to_ass_ts(e)},TikTok,,0,0,0,,{txt}\n")

print(f"[build_ass] écrit: {opath} (durée audio détectée: {audio_dur:.2f}s)")