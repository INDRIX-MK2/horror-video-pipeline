#!/usr/bin/env python3
import sys, argparse, pathlib, subprocess, re, math

# ----------------------------
# Arguments / options
# ----------------------------
ap = argparse.ArgumentParser(description="Génère un .ass avec Titre (centré), Histoire, et CTA (centré) + pauses.")
ap.add_argument("--transcript", required=True, help="Texte de l'histoire (sans didascalies)")
ap.add_argument("--audio", help="Audio complet (si tu n'utilises PAS les segments)")
ap.add_argument("--out", default="subs/captions.ass", help="Fichier .ass de sortie")

# Segments facultatifs (RECOMMANDÉ)
ap.add_argument("--title-text", default="story/title.txt", help="Fichier texte du titre")
ap.add_argument("--title-audio", default="audio/title.wav", help="Audio du titre")
ap.add_argument("--title-gap-after", type=float, default=2.0, help="Pause après le titre (secondes)")

ap.add_argument("--story-audio", default="audio/story.wav", help="Audio de l'histoire (si segmenté)")

ap.add_argument("--cta-text", default="story/cta.txt", help="Fichier texte du CTA")
ap.add_argument("--cta-audio", default="audio/cta.wav", help="Audio du CTA")
ap.add_argument("--gap-before-cta", type=float, default=1.0, help="Pause entre fin histoire et début CTA (secondes)")

# Styles
ap.add_argument("--font", default="Arial")
ap.add_argument("--size", type=int, default=60)

# Titre (centré, jaune, 4 mots/ligne)
ap.add_argument("--title-max-words", type=int, default=4)
ap.add_argument("--title-size", type=int, default=96)
ap.add_argument("--title-colour", default="&H00FFFF00")  # JAUNE (AABBGGRR; AA=00 opaque)
ap.add_argument("--title-align", type=int, default=5)    # centre-centre
ap.add_argument("--title-marginv", type=int, default=0)

# CTA (centré, jaune, 4 mots/ligne)
ap.add_argument("--cta-max-words", type=int, default=4)
ap.add_argument("--cta-size", type=int, default=80)
ap.add_argument("--cta-colour", default="&H00FFFF00")
ap.add_argument("--cta-align", type=int, default=5)
ap.add_argument("--cta-marginv", type=int, default=0)

# Histoire (sous-titres classiques)
ap.add_argument("--story-max-words-per-line", type=int, default=4)
ap.add_argument("--story-max-lines", type=int, default=3)
ap.add_argument("--story-align", type=int, default=5)    # tu peux passer à 2 si tu veux en bas-centre
ap.add_argument("--story-marginv", type=int, default=200)

args = ap.parse_args()

# ----------------------------
# Utilitaires
# ----------------------------
def exists_nonempty(p: pathlib.Path) -> bool:
    return p.exists() and p.is_file() and p.stat().st_size > 0

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
    cs = int(round((sec - math.floor(sec)) * 100))
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

def clean_text(s: str) -> str:
    # retire didascalies entre [] ou ()
    s = re.sub(r"\[[^\]]+\]", "", s)
    s = re.sub(r"\([^)]+\)", "", s)
    return re.sub(r"\s+", " ", s).strip()

def wrap_by_words(text: str, max_words: int) -> list[str]:
    words = text.split()
    out, buf = [], []
    for w in words:
        buf.append(w)
        if len(buf) >= max_words:
            out.append(" ".join(buf))
            buf = []
    if buf:
        out.append(" ".join(buf))
    return out

def split_sentences(txt: str) -> list[str]:
    # split "douce" par ponctuation forte
    parts = re.split(r'(?<=[\.\!\?…])\s+', txt)
    return [p.strip() for p in parts if p.strip()]

def make_story_chunks(text: str, max_words_per_line: int, max_lines: int) -> list[str]:
    # phrase -> lignes wrapées (max_words_per_line), puis join avec \N en respectant max_lines
    sentences = split_sentences(text)
    chunks = []
    for sent in sentences:
        lines = wrap_by_words(sent, max_words_per_line)
        # regrouper par paquets de max_lines
        for i in range(0, len(lines), max_lines):
            group = lines[i:i+max_lines]
            chunks.append(r"\N".join(group))
    # fallback si rien
    if not chunks:
        chunks = [text]
    return chunks

# ----------------------------
# Entrées / validations
# ----------------------------
tpath = pathlib.Path(args.transcript)
if not exists_nonempty(tpath):
    print("Transcript introuvable/vide", file=sys.stderr); sys.exit(1)

title_txt_path = pathlib.Path(args.title-text) if hasattr(args, "title-text") else pathlib.Path(args.title_text)
cta_txt_path   = pathlib.Path(args.cta-text)   if hasattr(args, "cta-text")   else pathlib.Path(args.cta_text)

title_wav = pathlib.Path(args.title_audio)
story_wav = pathlib.Path(args.story_audio)
cta_wav   = pathlib.Path(args.cta_audio)

opath = pathlib.Path(args.out)
opath.parent.mkdir(parents=True, exist_ok=True)

# ----------------------------
# Durées & placement temporel
# ----------------------------
# Mode 1 (recommandé): segments fournis => on calcule offsets précis
have_segments = all([
    exists_nonempty(story_wav),
    exists_nonempty(title_wav) or not exists_nonempty(title_txt_path),  # titre optionnel
    exists_nonempty(cta_wav)   or not exists_nonempty(cta_txt_path),    # cta optionnel
])

if have_segments:
    dur_title = ffprobe_duration(title_wav) if exists_nonempty(title_wav) else 0.0
    dur_story = ffprobe_duration(story_wav)
    dur_cta   = ffprobe_duration(cta_wav)   if exists_nonempty(cta_wav)   else 0.0

    t0_title = 0.0
    t1_title = t0_title + dur_title

    t0_story = t1_title + (args.title_gap_after if dur_title > 0 else 0.0)
    t1_story = t0_story + dur_story

    t0_cta   = t1_story + (args.gap_before_cta if dur_cta > 0 else 0.0)
    t1_cta   = t0_cta + dur_cta

    total_audio = t1_cta if dur_cta > 0 else t1_story

else:
    # Mode 2: un seul audio => tout est "story" (pas de titre/cta temporel possible automatiquement)
    if not args.audio:
        print("Erreur: ni segments ni --audio fournis. Donne --audio ou les WAV segmentés.", file=sys.stderr)
        sys.exit(1)
    audio_full = pathlib.Path(args.audio)
    if not exists_nonempty(audio_full):
        print(f"Audio introuvable/vide: {audio_full}", file=sys.stderr)
        sys.exit(1)
    total_audio = ffprobe_duration(audio_full)
    dur_title = dur_cta = 0.0
    t0_title = t1_title = 0.0
    t0_story = 0.0
    t1_story = total_audio
    t0_cta = t1_cta = 0.0

# ----------------------------
# Prépare les textes
# ----------------------------
story_raw  = clean_text(tpath.read_text(encoding="utf-8"))
title_text = clean_text(title_txt_path.read_text(encoding="utf-8")) if exists_nonempty(title_txt_path) else ""
cta_text   = clean_text(cta_txt_path.read_text(encoding="utf-8"))   if exists_nonempty(cta_txt_path)   else ""

# Wraps
title_lines = wrap_by_words(title_text, args.title_max_words) if dur_title > 0 and title_text else []
cta_lines   = wrap_by_words(cta_text,   args.cta_max_words)   if dur_cta > 0 and cta_text   else []

story_chunks = make_story_chunks(
    story_raw,
    max_words_per_line=args.story_max_words_per_line,
    max_lines=args.story_max_lines
)

# Répartition story sur sa durée
events = []
if story_chunks and (t1_story > t0_story):
    per = (t1_story - t0_story) / max(1, len(story_chunks))
    t = t0_story
    for ch in story_chunks:
        s = t
        e = min(t1_story, t + per)
        events.append(("TikTok", s, e, ch))
        t = e

# Titre (s'affiche tout seul avant l'histoire)
if dur_title > 0 and title_lines:
    title_text_joined = r"\N".join(title_lines)
    events.insert(0, ("Title", t0_title, t1_title, title_text_joined))
    # la pause entre titre et histoire est déjà dans t0_story (title_gap_after)

# CTA (1s après l'histoire, centré)
if dur_cta > 0 and cta_lines:
    cta_text_joined = r"\N".join(cta_lines)
    events.append(("CTA", t0_cta, t1_cta, cta_text_joined))

# ----------------------------
# Header ASS + styles
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
Style: TikTok,{args.font},{args.size},&H00FFFF00,&H00000000,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,3,2,{args.story_align},40,40,{args.story_marginv},1
Style: Title,{args.font},{args.title_size},{args.title_colour},&H00000000,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,3,2,{args.title_align},40,40,{args.title_marginv},1
Style: CTA,{args.font},{args.cta_size},{args.cta_colour},&H00000000,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,3,2,{args.cta_align},40,40,{args.cta_marginv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".replace("\r\n","\n")

# ----------------------------
# Écriture
# ----------------------------
with opath.open("w", encoding="utf-8") as f:
    f.write(hdr)
    for style, s, e, txt in events:
        f.write(f"Dialogue: 0,{to_ass_ts(s)},{to_ass_ts(e)},{style},,0,0,0,,{txt}\n")

print(f"[build_ass] écrit: {opath} (durée totale audio ~ {total_audio:.2f}s)")
if have_segments:
    print(f"[segments] title=({t0_title:.2f}-{t1_title:.2f}) story=({t0_story:.2f}-{t1_story:.2f}) cta=({t0_cta:.2f}-{t1_cta:.2f})")
else:
    print("[mode] audio unique: pas de placement auto pour titre/cta (fournis segments pour activer).")