#!/usr/bin/env python3
# coding: utf-8
import argparse, pathlib, subprocess, sys, re

# -------- Utils --------
def ffprobe_duration(path: pathlib.Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error",
            "-show_entries","format=duration",
            "-of","default=nk=1:nw=1",
            str(path)
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
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

def split_sentences(text: str):
    # coupe sur . ! ? … (en gardant la ponctuation)
    text = text.replace("\r","")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    parts = re.split(r'(?<=[\.\!\?\…])\s+', text)
    parts = [p.strip() for p in parts if p.strip()]
    return parts

def wrap_words_to_lines(words, max_words_per_line: int, max_lines: int):
    """Retourne la chaîne ASS avec \\N entre lignes, max n lignes."""
    lines, buf = [], []
    for w in words:
        buf.append(w)
        if len(buf) >= max_words_per_line:
            lines.append(" ".join(buf))
            buf = []
            if len(lines) >= max_lines:
                # s'il reste des mots, on les ajoute à la dernière ligne
                lines[-1] += (" " + " ".join(buf)) if buf else ""
                buf = []
                break
    if buf:
        lines.append(" ".join(buf))
    # jointure ASS pour retour à la ligne
    return r"\N".join(lines[:max_lines])

def count_words(s: str) -> int:
    return len(s.split())

# -------- CLI --------
ap = argparse.ArgumentParser(description="Build centered ASS subtitles (title/story/cta-ready) with anti-drift.")
ap.add_argument("--transcript", required=True, help="Fichier texte (histoire uniquement dans ce script).")
ap.add_argument("--audio", required=True, help="WAV/MP3 correspondant à la narration finale (title + story + cta si enchaînés).")
ap.add_argument("--out", default="subs/captions.ass", help="Fichier ASS de sortie.")
ap.add_argument("--font", default="Arial")
ap.add_argument("--size", type=int, default=60)
ap.add_argument("--colour", default="&H0000FFFF", help="ASS PrimaryColour (ex: &H0000FFFF = jaune vif).")
ap.add_argument("--outline-colour", default="&H00000000")
ap.add_argument("--back-colour", default="&H64000000")
ap.add_argument("--outline", type=float, default=3.0)
ap.add_argument("--shadow", type=float, default=2.0)
ap.add_argument("--align", type=int, default=5, help="ASS Alignment (5 = centre bas).")
ap.add_argument("--marginv", type=int, default=200)
ap.add_argument("--max-words", type=int, default=4, help="Mots max par ligne.")
ap.add_argument("--max-lines", type=int, default=3, help="Lignes max (2-3 conseillé).")
ap.add_argument("--lead", type=float, default=0.00, help="Décalage d’ancrage (s) pour anti-dérive (+avance, -retard).")
ap.add_argument("--speed", type=float, default=1.00, help="Facteur vitesse (1.0 = proportionalité exacte, >1 = plus lent).")

args = ap.parse_args()

tpath = pathlib.Path(args.transcript)
apath = pathlib.Path(args.audio)
opath = pathlib.Path(args.out)
opath.parent.mkdir(parents=True, exist_ok=True)

if not tpath.exists() or not tpath.stat().st_size:
    print("Transcript introuvable/vide", file=sys.stderr); sys.exit(1)
if not apath.exists() or not apath.stat().st_size:
    print("Audio introuvable/vide", file=sys.stderr); sys.exit(1)

# -------- Lecture données --------
raw = tpath.read_text(encoding="utf-8")
# on enlève les crochets/didascalies s'il y en a
raw = re.sub(r"\[[^\]]+\]", "", raw)
raw = re.sub(r"\([^)]+\)", "", raw)
sentences = split_sentences(raw)

if not sentences:
    print("Aucune phrase détectée dans le transcript.", file=sys.stderr)
    # on force quand même une ligne
    sentences = [raw.strip()]

audio_dur = max(0.01, ffprobe_duration(apath))

# -------- Timing anti-drift (proportionnel au nombre de mots) --------
# total mots
total_words = sum(count_words(s) for s in sentences) or 1
# durée par mot, modulée par speed (speed>1 => plus de temps par mot)
per_word = (audio_dur / total_words) * float(args.speed)

# événements (start, end, text_ass)
events = []
t = 0.0 + float(args.lead)
min_dur = 0.40  # sécurité lecture
for i, s in enumerate(sentences):
    wc = max(1, count_words(s))
    dur = max(min_dur, wc * per_word)
    s_start = max(0.0, t)
    s_end   = min(audio_dur, s_start + dur)

    # wrap sur 2-3 lignes, 4 mots max/ligne (paramétrable)
    txt_ass = wrap_words_to_lines(s.split(), max(args.max_words,1), max(args.max_lines,1))
    # pas de backslash inutile à la fin, on a uniquement \N au milieu si besoin
    events.append((s_start, s_end, txt_ass))
    t = s_end

# S'assure que le dernier s'aligne pile à la fin pour éviter le glissement visuel
if events:
    last = list(events[-1])
    if last[1] < audio_dur:
        last[1] = audio_dur
        events[-1] = tuple(last)

# -------- En-tête ASS --------
hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTok,{args.font},{args.size},{args.colour},&H00000000,{args.outline-colour},{args.back-colour},0,0,0,0,100,100,0,0,1,{args.outline},{args.shadow},{args.align},40,40,{args.marginv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".replace("\r\n","\n")

# ------ Écriture ------
with opath.open("w", encoding="utf-8") as f:
    f.write(hdr)
    for s_start, s_end, txt_ass in events:
        f.write(f"Dialogue: 0,{to_ass_ts(s_start)},{to_ass_ts(s_end)},TikTok,,0,0,0,,{txt_ass}\n")

print(f"[build_ass] écrit: {opath} (durée audio détectée: {audio_dur:.2f}s)")
