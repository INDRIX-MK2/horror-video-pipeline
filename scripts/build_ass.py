#!/usr/bin/env python3
import sys, argparse, pathlib, subprocess, re, math, json
from typing import Tuple, Optional, Any, List

# ----------------------------
# Arguments / options
# ----------------------------
ap = argparse.ArgumentParser(description="Génère un .ass avec Titre (centré), Histoire, et CTA (centré) + pauses.")
ap.add_argument("--transcript", required=True, help="Texte de l'histoire (sans didascalies)")
ap.add_argument("--audio", help="Audio complet (si tu n'utilises PAS les segments)")
ap.add_argument("--out", default="subs/captions.ass", help="Fichier .ass de sortie")

# Segments facultatifs (RECOMMANDÉ)
ap.add_argument("--title-text", dest="title_text", default="story/title.txt", help="Fichier texte du titre")
ap.add_argument("--title-audio", dest="title_audio", default="audio/title.wav", help="Audio du titre")
ap.add_argument("--title-gap-after", type=float, default=2.0, help="Pause après le titre (secondes)")

ap.add_argument("--story-audio", dest="story_audio", default="audio/story.wav", help="Audio de l'histoire (si segmenté)")

ap.add_argument("--cta-text", dest="cta_text", default="story/cta.txt", help="Fichier texte du CTA")
ap.add_argument("--cta-audio", dest="cta_audio", default="audio/cta.wav", help="Audio du CTA")
ap.add_argument("--gap-before-cta", type=float, default=1.0, help="Pause entre fin histoire et début CTA (secondes)")

# timeline JSON optionnel (prend la priorité sur la sonde audio)
ap.add_argument("--timeline", help="JSON avec timings. Ex: {'title':{'start':0,'end':2}, 'story':{'start':2,'end':92}, 'cta':{'start':93,'end':98}}")

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
ap.add_argument("--story-align", type=int, default=5)    # 5 = centre-centre (mets 2 pour bas-centre)
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
            "of=default=nk=1:nw=1".replace("of=","-of="), str(p)
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
    s = re.sub(r"\[[^\]]+\]", "", s)
    s = re.sub(r"\([^)]+\)", "", s)
    return re.sub(r"\s+", " ", s).strip()

def wrap_by_words(text: str, max_words: int) -> List[str]:
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

def split_sentences(txt: str) -> List[str]:
    parts = re.split(r'(?<=[\.\!\?…])\s+', txt)
    return [p.strip() for p in parts if p.strip()]

def make_story_chunks(text: str, max_words_per_line: int, max_lines: int) -> List[str]:
    sentences = split_sentences(text)
    chunks = []
    for sent in sentences:
        lines = wrap_by_words(sent, max_words_per_line)
        for i in range(0, len(lines), max_lines):
            group = lines[i:i+max_lines]
            # Utiliser \N pour forcer la nouvelle ligne ASS, sans échappement résiduel
            chunks.append("\\N".join(group))
    if not chunks:
        chunks = [text]
    return chunks

# ----------------------------
# Entrées / validations
# ----------------------------
tpath = pathlib.Path(args.transcript)
if not exists_nonempty(tpath):
    print("Transcript introuvable/vide", file=sys.stderr); sys.exit(1)

title_txt_path = pathlib.Path(args.title_text)
cta_txt_path   = pathlib.Path(args.cta_text)

title_wav = pathlib.Path(args.title_audio)
story_wav = pathlib.Path(args.story_audio)
cta_wav   = pathlib.Path(args.cta_audio)

opath = pathlib.Path(args.out)
opath.parent.mkdir(parents=True, exist_ok=True)

timeline_path = pathlib.Path(args.timeline) if args.timeline else None
timeline: Optional[dict] = None
if timeline_path and exists_nonempty(timeline_path):
    try:
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[build_ass] Attention: timeline illisible: {e}", file=sys.stderr)
        timeline = None

# ----------------------------
# Durées & placement temporel
# ----------------------------
def parse_tl_section(val: Any, prev_end: float, default_gap: float) -> Tuple[float,float,bool]:
    """
    Accepte:
      - dict: {start,end} | {start,duration} | {duration}
      - nombre: duration
      - liste/tuple de 2 nombres: [start, end] ou [start, duration] (si end<start => duration)
    Retourne (start, end, found).
    """
    start: Optional[float] = None
    end:   Optional[float] = None
    dur:   Optional[float] = None

    if isinstance(val, dict):
        if "start" in val: start = float(val["start"])
        if "end"   in val: end   = float(val["end"])
        if "duration" in val: dur = float(val["duration"])
    elif isinstance(val, (int, float)):
        dur = float(val)
    elif isinstance(val, (list, tuple)) and len(val) == 2 and all(isinstance(x, (int,float)) for x in val):
        a, b = float(val[0]), float(val[1])
        # si b > a on considère [start,end], sinon [start,duration]
        if b > a:
            start, end = a, b
        else:
            start, dur = a, b
    else:
        return (0.0, 0.0, False)

    if start is None:
        start = prev_end + (default_gap if default_gap is not None else 0.0)
    if end is None:
        if dur is not None:
            end = start + dur
        else:
            return (0.0, 0.0, False)

    return (float(start), float(end), True)

def seg_from_timeline(name: str, prev_end: float, default_gap: float) -> Tuple[float,float,bool]:
    if not timeline or name not in timeline:
        return (0.0, 0.0, False)
    return parse_tl_section(timeline[name], prev_end, default_gap)

have_segments = False
t0_title=t1_title=t0_story=t1_story=t0_cta=t1_cta=0.0
dur_title=dur_story=dur_cta=0.0
total_audio=0.0

if timeline:
    # Titre
    t0_title, t1_title, f_title = seg_from_timeline("title", 0.0, 0.0)
    dur_title = max(0.0, t1_title - t0_title) if f_title else 0.0
    # Histoire (gap après titre si start absent)
    t0_story, t1_story, f_story = seg_from_timeline("story", t1_title, args.title_gap_after)
    dur_story = max(0.0, t1_story - t0_story) if f_story else 0.0
    # CTA (gap avant CTA si start absent)
    t0_cta, t1_cta, f_cta = seg_from_timeline("cta", t1_story, args.gap_before_cta)
    dur_cta = max(0.0, t1_cta - t0_cta) if f_cta else 0.0

    total_audio = max(t1_cta, t1_story, t1_title)
    have_segments = True

else:
    # Ancien comportement: on sonde les WAV si présents
    have_segments = all([
        exists_nonempty(story_wav),
        exists_nonempty(title_wav) or not exists_nonempty(title_txt_path),
        exists_nonempty(cta_wav)   or not exists_nonempty(cta_txt_path),
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
        # audio unique
        if not args.audio:
            print("Erreur: ni timeline, ni segments, ni --audio fournis.", file=sys.stderr)
            sys.exit(1)
        audio_full = pathlib.Path(args.audio)
        if not exists_nonempty(audio_full):
            print(f"Audio introuvable/vide: {audio_full}", file=sys.stderr)
            sys.exit(1)
        total_audio = ffprobe_duration(audio_full)
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

title_lines = wrap_by_words(title_text, args.title_max_words) if (t1_title > t0_title and title_text) else []
cta_lines   = wrap_by_words(cta_text,   args.cta_max_words)   if (t1_cta   > t0_cta   and cta_text)   else []
story_chunks = make_story_chunks(
    story_raw,
    max_words_per_line=args.story_max_words_per_line,
    max_lines=args.story_max_lines
)

# ----------------------------
# Événements (timing)
# ----------------------------
events = []

# Story répartie uniformément sur sa fenêtre temporelle
if story_chunks and (t1_story > t0_story):
    per = (t1_story - t0_story) / max(1, len(story_chunks))
    t = t0_story
    for ch in story_chunks:
        s = t
        e = min(t1_story, t + per)
        events.append(("TikTok", s, e, ch))
        t = e

# Titre avant l’histoire
if (t1_title > t0_title) and title_lines:
    title_text_joined = "\\N".join(title_lines)
    events.insert(0, ("Title", t0_title, t1_title, title_text_joined))

# CTA après la pause
if (t1_cta > t0_cta) and cta_lines:
    cta_text_joined = "\\N".join(cta_lines)
    events.append(("CTA", t0_cta, t1_cta, cta_text_joined))

# ----------------------------
# Styles ASS
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
with pathlib.Path(args.out).open("w", encoding="utf-8") as f:
    f.write(hdr)
    for style, s, e, txt in events:
        f.write(f"Dialogue: 0,{to_ass_ts(s)},{to_ass_ts(e)},{style},,0,0,0,,{txt}\n")

print(f"[build_ass] écrit: {args.out} (durée totale ~ {total_audio:.2f}s)")
if timeline:
    print("[mode] timeline.json utilisé (prioritaire).")
elif exists_nonempty(story_wav):
    print(f"[segments] title=({t0_title:.2f}-{t1_title:.2f}) story=({t0_story:.2f}-{t1_story:.2f}) cta=({t0_cta:.2f}-{t1_cta:.2f})")
else:
    print("[mode] audio unique: story sur toute la durée.")