#!/usr/bin/env python3
import sys
import argparse
import pathlib
import subprocess
import re

# === Arguments en ligne de commande ===
ap = argparse.ArgumentParser(description="Génère un fichier ASS de sous-titres")
ap.add_argument("--transcript", required=True, help="Fichier texte contenant la transcription complète")
ap.add_argument("--audio", required=True, help="Fichier audio pour calculer la durée totale")
ap.add_argument("--out", default="subs/captions.ass", help="Fichier de sortie ASS")
ap.add_argument("--font", default="Arial", help="Police utilisée pour les sous-titres")
ap.add_argument("--size", type=int, default=60, help="Taille de la police des sous-titres")
ap.add_argument("--words-line", type=int, default=4, help="Nombre max de mots par ligne")
args = ap.parse_args()

# === Préparation des chemins ===
tpath = pathlib.Path(args.transcript)
apath = pathlib.Path(args.audio)
opath = pathlib.Path(args.out)
opath.parent.mkdir(parents=True, exist_ok=True)

if not tpath.exists() or not tpath.stat().st_size:
    print("Transcript introuvable ou vide", file=sys.stderr)
    sys.exit(1)

if not apath.exists() or not apath.stat().st_size:
    print("Audio introuvable ou vide", file=sys.stderr)
    sys.exit(1)

# === Durée audio avec ffprobe ===
def dur_audio(p):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nk=1:nw=1", str(p)
    ]).decode("utf-8", "ignore").strip()
    try:
        return float(out)
    except:
        return 0.0

# === Formatage timestamps ASS ===
def to_ass_ts(sec):
    if sec < 0:
        sec = 0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))  # centisecondes
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

# === Lecture et nettoyage du transcript ===
raw = tpath.read_text(encoding="utf-8")
raw = re.sub(r"\[[^\]]+\]", "", raw)      # supprime [didascalies]
raw = re.sub(r"\([^)]+\)", "", raw)       # supprime (didascalies)
sentences = [ln.strip() for ln in raw.split('.') if ln.strip()]

# === Durée audio détectée ===
audio_dur = max(0.01, dur_audio(apath))

# === Découpage du transcript en phrases et sous-lignes ===
chunks = []
for sentence in sentences:
    words = sentence.split()
    buf = []
    for w in words:
        buf.append(w)
        if len(buf) >= args.words_line:
            chunks.append(" ".join(buf))
            buf = []
    if buf:
        chunks.append(" ".join(buf))

# === Répartition du temps par chunk ===
n = max(1, len(chunks))
per = audio_dur / n
events = []
t = 0.0
for text in chunks:
    s = t
    e = min(audio_dur, t + per)
    events.append((s, e, text))
    t = e

# === Header ASS ===
hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTok,{args.font},{args.size},&H007FFF00,&H00000000,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,3,2,5,40,40,200,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".replace("\r\n", "\n")

# === Écriture du fichier ASS ===
with opath.open("w", encoding="utf-8") as f:
    f.write(hdr)
    for s, e, txt in events:
        f.write(f"Dialogue: 0,{to_ass_ts(s)},{to_ass_ts(e)},TikTok,,0,0,0,,{txt}\n")

print(f"[build_ass] écrit: {opath} (durée audio détectée: {audio_dur:.2f}s)")