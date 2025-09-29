#!/usr/bin/env python3
import sys, argparse, pathlib, subprocess, re, math

# -----------------------------
#  Helpers
# -----------------------------
def ffprobe_duration(p: pathlib.Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error","-show_entries","format=duration",
            "-of","default=nk=1:nw=1", str(p)
        ]).decode("utf-8","ignore").strip()
        return float(out)
    except Exception:
        return 0.0

def to_ass_ts(sec: float) -> str:
    if sec < 0: sec = 0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    if cs >= 100:
        s += 1
        cs = 0
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

def sanitize_text(s: str) -> str:
    # enlève didascalies entre [] ou ()
    s = re.sub(r"\[[^\]]+\]", "", s)
    s = re.sub(r"\([^)]+\)", "", s)
    s = s.strip()
    # retire espaces multiples
    s = re.sub(r"\s+", " ", s)
    return s

def split_sentences(text: str) -> list[str]:
    # coupe par phrase sur . ! ? ; : (en conservant le séparateur)
    chunks = re.split(r'([.!?;:])', text)
    out = []
    buf = ""
    for part in chunks:
        if part in [".","!","?",";",":"]:
            buf += part
            if buf.strip():
                out.append(buf.strip())
            buf = ""
        else:
            buf += part
    if buf.strip():
        out.append(buf.strip())
    # filtre les phrases vides
    out = [x for x in out if x]
    return out

def wrap_words(words: list[str], max_words: int, max_lines: int) -> list[str]:
    """Retourne de 1 à max_lines lignes avec <= max_words par ligne. Insertions \\N entre lignes (pas de backslash final)."""
    lines = []
    i = 0
    total = len(words)
    while i < total and len(lines) < max_lines:
        j = min(i + max_words, total)
        line_words = words[i:j]
        lines.append(" ".join(line_words))
        i = j
    # si reste des mots non affichés, on les “compresse” sur la dernière ligne
    if i < total and lines:
        rest = " ".join(words[i:])
        lines[-1] = (lines[-1] + " " + rest).strip()
    return lines

def make_ass_dialogue(start: float, end: float, style: str, text_lines: list[str]) -> str:
    # jointure lignes avec \N (ASS line break). AUCUN backslash final.
    txt = r"\N".join(text_lines)
    return f"Dialogue: 0,{to_ass_ts(start)},{to_ass_ts(end)},{style},,0,0,0,,{txt}\n"

# -----------------------------
#  Main
# -----------------------------
ap = argparse.ArgumentParser(description="Build ASS subtitles from transcript and audio duration")
ap.add_argument("--transcript", required=True, help="Chemin du texte narratif (SANS didascalies)")
ap.add_argument("--audio", required=True, help="Chemin de l'audio (pour durée)")
ap.add_argument("--out", default="subs/captions.ass", help="Fichier ASS de sortie")
ap.add_argument("--font", default="Arial")
ap.add_argument("--size", type=int, default=60)           # <- taille modifiable
ap.add_argument("--align", type=int, default=5)           # 5 = centre bas
ap.add_argument("--margin-v", type=int, default=120)      # marge verticale (pixels)
ap.add_argument("--max-words", type=int, default=5)       # mots max par ligne
ap.add_argument("--max-lines", type=int, default=3)       # lignes max par sous-titre
ap.add_argument("--lead", type=float, default=0.0)        # avance (+) ou retard (-) global en secondes
ap.add_argument("--speed", type=float, default=1.0)       # factor temps (1.0 = normal)
ap.add_argument("--primary", default="&H007FFF00")        # jaune pâle
ap.add_argument("--outline", default="&H00000000")        # contour noir
ap.add_argument("--shadow", type=int, default=2)          # ombre
ap.add_argument("--outline-size", type=int, default=3)    # épaisseur du contour
args = ap.parse_args()

tpath = pathlib.Path(args.transcript)
apath = pathlib.Path(args.audio)
opath = pathlib.Path(args.out)
opath.parent.mkdir(parents=True, exist_ok=True)

if not tpath.exists() or not tpath.stat().st_size:
    print("Transcript introuvable/vide", file=sys.stderr); sys.exit(1)
if not apath.exists() or not apath.stat().st_size:
    print("Audio introuvable/vide", file=sys.stderr); sys.exit(1)

audio_dur = max(0.01, ffprobe_duration(apath))

raw = tpath.read_text(encoding="utf-8")
raw = sanitize_text(raw)

# 1) phrases
sentences = split_sentences(raw)
if not sentences:
    sentences = [raw]

# 2) compter mots totaux (pondération des durées)
def wc(s: str) -> int:
    return len(s.split())

total_words = sum(wc(s) for s in sentences) or 1

# 3) timeline de base proportionnelle au nb de mots
events = []
t = 0.0
for s in sentences:
    n = wc(s)
    dur = (n / total_words) * audio_dur
    start = t
    end = min(audio_dur, start + dur)
    events.append((start, end, s))
    t = end

# 4) anti-dérive simple (lead+speed) et clamp
adj_events = []
for (s,e,txt) in events:
    s = args.lead + s * args.speed
    e = args.lead + e * args.speed
    s = max(0.0, min(s, audio_dur))
    e = max(s + 0.05, min(e, audio_dur))  # au moins 50 ms
    adj_events.append((s,e,txt))

# 5) wrap par lignes (2-3 lignes, 4-5 mots/ligne)
style_name = "TikTok"
ass_hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: {style_name},{args.font},{args.size},{args.primary},&H00000000,{args.outline},&H64000000,0,0,0,0,100,100,0,0,1,{args.outline_size},{args.shadow},{args.align},40,40,{args.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".replace("\r\n","\n")

with opath.open("w", encoding="utf-8") as f:
    f.write(ass_hdr)
    for (s,e,txt) in adj_events:
        words = txt.split()
        lines = wrap_words(words, max(1,args.max_words), max(1,args.max_lines))
        f.write(make_ass_dialogue(s, e, style_name, lines))

print(f"[build_ass] écrit: {opath} (durée audio détectée: {audio_dur:.2f}s)")