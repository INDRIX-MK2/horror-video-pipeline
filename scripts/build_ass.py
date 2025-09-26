#!/usr/bin/env python3
import sys, argparse, pathlib, subprocess, re
from typing import List, Tuple

ap = argparse.ArgumentParser(description="Construit un .ass simple synchronisé sur la durée audio")
ap.add_argument("--transcript", required=True, help="Texte narratif (story.txt)")
ap.add_argument("--audio",      required=True, help="Fichier audio (voice.wav)")
ap.add_argument("--out",        default="subtitles/captions.ass", help="Sortie .ass")
ap.add_argument("--font",       default="Arial", help="Police")
ap.add_argument("--size",       type=int, default=80, help="Taille police")
ap.add_argument("--offset",     type=float, default=0.0,
                help="Décalage global en secondes (positif = sous-titres plus tard)")
args = ap.parse_args()

tpath = pathlib.Path(args.transcript)
apath = pathlib.Path(args.audio)
opath = pathlib.Path(args.out)
opath.parent.mkdir(parents=True, exist_ok=True)

if not tpath.exists() or not tpath.stat().st_size:
    print("Transcript introuvable/vide", file=sys.stderr); sys.exit(1)
if not apath.exists() or not apath.stat().st_size:
    print("Audio introuvable/vide", file=sys.stderr); sys.exit(1)

def dur_audio(p: pathlib.Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error","-show_entries","format=duration",
            "-of","default=nk=1:nw=1", str(p)
        ]).decode("utf-8","ignore").strip()
        return float(out)
    except Exception:
        return 0.0

def to_ass_ts(sec: float) -> str:
    if sec < 0: sec = 0.0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

audio_dur = max(0.01, dur_audio(apath))

# ==========================
#  Lecture + segmentation en phrases
# ==========================
raw = tpath.read_text(encoding="utf-8")

# On retire les didascalies / apartés éventuels
raw = re.sub(r"\[[^\]]+\]", "", raw)
raw = re.sub(r"\([^)]+\)", "", raw)

# Split en phrases, en gardant la ponctuation
sentences: List[str] = []
buf = []
for token in re.split(r"(\.|\!|\?|…)", raw):
    if token is None:
        continue
    token = token.strip()
    if not token:
        continue
    buf.append(token)
    # si le token est une ponctuation forte, on ferme la phrase
    if token in [".", "!", "?", "…"]:
        sentences.append("".join(buf).strip())
        buf = []
if buf:
    sentences.append(" ".join(buf).strip())

# Fallback si jamais rien
if not sentences:
    sentences = [ln.strip() for ln in raw.splitlines() if ln.strip()]

# ==========================
#  Découpe chaque phrase en lignes (4-5 mots max, 2-3 lignes)
# ==========================
def wrap_words(phrase: str, max_words: int = 5, max_lines: int = 3) -> List[str]:
    ws = phrase.split()
    if not ws:
        return []
    lines = []
    cur = []
    for w in ws:
        cur.append(w)
        if len(cur) >= max_words:
            lines.append(" ".join(cur)); cur = []
            if len(lines) >= max_lines:
                # si trop longue, on continue en “débordement” ligne par ligne
                pass
    if cur:
        lines.append(" ".join(cur))
    # si on dépasse max_lines, on fusionne la fin pour ne garder que max_lines
    if len(lines) > max_lines:
        head = lines[:max_lines-1]
        tail = " ".join(lines[max_lines-1:])
        lines = head + [tail]
    return lines

wrapped_sentences: List[List[str]] = [wrap_words(s, 5, 3) for s in sentences]
wrapped_sentences = [ls for ls in wrapped_sentences if ls]  # enlève vides

# ==========================
#  Timing : proportionnel au nb de mots
# ==========================
def count_words(lines: List[str]) -> int:
    return sum(len(l.split()) for l in lines)

total_words = sum(count_words(ls) for ls in wrapped_sentences) or 1
min_line = 0.60  # minimum par ligne pour lisibilité
events: List[Tuple[float, float, str]] = []

t = 0.0
for lines in wrapped_sentences:
    words_here = count_words(lines)
    dur_here = max(len(lines) * min_line, audio_dur * (words_here / total_words))
    # répartit équitablement entre les lignes de la phrase
    per_line = max(min_line, dur_here / max(1, len(lines)))
    for ln in lines:
        s = t
        e = min(audio_dur, s + per_line)
        events.append((s, e, ln))
        t = e

# Si on a un petit reliquat de temps audio, on l'ajoute à la dernière ligne
if events and t < audio_dur:
    s, e, txt = events[-1]
    events[-1] = (s, audio_dur, txt)

# ==========================
#  Header ASS (style TikTok centré bas, jaune pâle)
#  PrimaryColour: &H00BBGGRR (0x00 alpha = opaque)
#  Ici: &H007FFF00 ~ jaune pâle
#  Outline=3, Shadow=2, Alignment=5 (bas-centré)
# ==========================
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
""".replace("\r\n","\n")

# ==========================
#  Écriture avec offset global
# ==========================
def clamp0(x: float) -> float:
    return x if x > 0 else 0.0

with opath.open("w", encoding="utf-8") as f:
    f.write(hdr)
    for s, e, txt in events:
        s += args.offset; e += args.offset
        s = clamp0(s);    e = clamp0(e)
        f.write(f"Dialogue: 0,{to_ass_ts(s)},{to_ass_ts(e)},TikTok,,0,0,0,,{txt}\n")

print(f"[build_ass] écrit: {opath} (durée audio détectée: {audio_dur:.2f}s)")