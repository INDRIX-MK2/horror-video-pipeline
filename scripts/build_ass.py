#!/usr/bin/env python3
import sys, argparse, pathlib, subprocess, re, math, json
from typing import Tuple, Optional, Any, List

ap = argparse.ArgumentParser(description="Génère un .ass avec Titre (centre), Histoire, CTA (centre) + pauses.")
ap.add_argument("--transcript", required=True, help="Texte de l'histoire (sans didascalies)")
ap.add_argument("--audio", help="Audio complet si non segmenté")
ap.add_argument("--out", default="subs/captions.ass", help="Fichier .ass de sortie")

# Segments (recommandé)
ap.add_argument("--title-text", default="story/title.txt")
ap.add_argument("--title-audio", default="audio/title.wav")
ap.add_argument("--title-gap-after", type=float, default=1.0, help="Pause après le titre (s)")

ap.add_argument("--story-audio", default="audio/story.wav")

ap.add_argument("--cta-text", default="story/cta.txt")
ap.add_argument("--cta-audio", default="audio/cta.wav")
ap.add_argument("--gap-before-cta", type=float, default=1.0, help="Pause avant CTA (s)")

# Timeline JSON (prioritaire si fourni)
ap.add_argument("--timeline", help="JSON: {'title':{...}, 'story':{...}, 'cta':{...}}")

# Styles globaux
ap.add_argument("--font", default="Arial")
ap.add_argument("--size", type=int, default=60)

# Titre (centre, jaune, 4 mots/ligne)
ap.add_argument("--title-max-words", type=int, default=4)
ap.add_argument("--title-size", type=int, default=96)
ap.add_argument("--title-colour", default="&H00FFFF00")     # jaune
ap.add_argument("--title-align", type=int, default=5)       # centre-centre
ap.add_argument("--title-marginv", type=int, default=0)

# CTA (centre, jaune, 4 mots/ligne)
ap.add_argument("--cta-max-words", type=int, default=4)
ap.add_argument("--cta-size", type=int, default=80)
ap.add_argument("--cta-colour", default="&H00FFFF00")
ap.add_argument("--cta-align", type=int, default=5)
ap.add_argument("--cta-marginv", type=int, default=0)

# Histoire (2–3 lignes, 4–5 mots/ligne selon ton réglage)
ap.add_argument("--story-max-words-per-line", type=int, default=4)
ap.add_argument("--story-max-lines", type=int, default=3)
ap.add_argument("--story-align", type=int, default=5)       # centre-centre (mets 2 pour bas-centre)
ap.add_argument("--story-marginv", type=int, default=200)

# Anti-décalage fin (micro-ajustements)
ap.add_argument("--lead", type=float, default=-0.06, help="Décalage début par ligne (s, négatif = plus tôt)")
ap.add_argument("--shrink", type=float, default=0.12, help="Réduction fin par ligne (s)")

args = ap.parse_args()

def exists_nonempty(p: pathlib.Path) -> bool:
    return p.exists() and p.is_file() and p.stat().st_size > 0

def ffprobe_duration(p: pathlib.Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error",
            "-show_entries","format=duration",
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
    s = re.sub(r"\[[^\]]+\]", "", s)
    s = re.sub(r"\([^)]+\)", "", s)
    return re.sub(r"\s+", " ", s).strip()

def wrap_by_words(text: str, max_words: int) -> List[str]:
    words = text.split()
    out, buf = [], []
    for w in words:
        buf.append(w)
        if len(buf) >= max_words:
            out.append(" ".join(buf)); buf=[]
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
            chunks.append("\\N".join(group))  # vrai saut de ligne ASS
    if not chunks:
        chunks = [text]
    return chunks

# Entrées
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

timeline = None
if args.timeline:
    tp = pathlib.Path(args.timeline)
    if exists_nonempty(tp):
        try:
            timeline = json.loads(tp.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[build_ass] timeline illisible: {e}", file=sys.stderr)

# Placement temporel
def parse_tl_section(val: Any, prev_end: float, default_gap: float) -> Tuple[float,float,bool]:
    start = end = dur = None
    if isinstance(val, dict):
        start = float(val.get("start")) if "start" in val else None
        end   = float(val.get("end"))   if "end"   in val else None
        dur   = float(val.get("duration")) if "duration" in val else None
    elif isinstance(val, (int,float)):
        dur = float(val)
    elif isinstance(val, (list,tuple)) and len(val) == 2 and all(isinstance(x,(int,float)) for x in val):
        a, b = float(val[0]), float(val[1])
        if b > a: start, end = a, b
        else:     start, dur = a, b
    else:
        return (0.0, 0.0, False)

    if start is None:
        start = prev_end + (default_gap or 0.0)
    if end is None:
        if dur is None: return (0.0,0.0,False)
        end = start + dur
    return (float(start), float(end), True)

def seg_from_timeline(name: str, prev_end: float, default_gap: float) -> Tuple[float,float,bool]:
    if not timeline or name not in timeline: return (0.0,0.0,False)
    return parse_tl_section(timeline[name], prev_end, default_gap)

have_segments = False
t0_title=t1_title=t0_story=t1_story=t0_cta=t1_cta=0.0
dur_title=dur_story=dur_cta=0.0
total_audio=0.0

if timeline:
    t0_title, t1_title, f_title = seg_from_timeline("title", 0.0, 0.0)
    dur_title = max(0.0, t1_title - t0_title) if f_title else 0.0

    t0_story, t1_story, f_story = seg_from_timeline("story", t1_title, args.title_gap_after)
    dur_story = max(0.0, t1_story - t0_story) if f_story else 0.0

    t0_cta, t1_cta, f_cta = seg_from_timeline("cta", t1_story, args.gap_before_cta)
    dur_cta = max(0.0, t1_cta - t0_cta) if f_cta else 0.0

    total_audio = max(t1_title, t1_story, t1_cta)
    have_segments = True
else:
    have_segments = all([
        exists_nonempty(story_wav),
        exists_nonempty(title_wav) or not exists_nonempty(title_txt_path),
        exists_nonempty(cta_wav)   or not exists_nonempty(cta_txt_path),
    ])
    if have_segments:
        dur_title = ffprobe_duration(title_wav) if exists_nonempty(title_wav) else 0.0
        dur_story = ffprobe_duration(story_wav)
        dur_cta   = ffprobe_duration(cta_wav)   if exists_nonempty(cta_wav)   else 0.0

        t0_title = 0.0; t1_title = t0_title + dur_title
        t0_story = t1_title + (args.title_gap_after if dur_title>0 else 0.0); t1_story = t0_story + dur_story
        t0_cta   = t1_story + (args.gap_before_cta if dur_cta>0 else 0.0);   t1_cta   = t0_cta + dur_cta
        total_audio = t1_cta if dur_cta>0 else t1_story
    else:
        if not args.audio:
            print("Erreur: ni timeline, ni segments, ni --audio.", file=sys.stderr); sys.exit(1)
        audio_full = pathlib.Path(args.audio)
        if not exists_nonempty(audio_full):
            print(f"Audio introuvable: {audio_full}", file=sys.stderr); sys.exit(1)
        total_audio = ffprobe_duration(audio_full)
        t0_title=t1_title=0.0
        t0_story=0.0; t1_story=total_audio
        t0_cta=t1_cta=0.0

# Textes
story_raw  = clean_text(pathlib.Path(args.transcript).read_text(encoding="utf-8"))
title_txt  = clean_text(pathlib.Path(args.title_text).read_text(encoding="utf-8")) if exists_nonempty(pathlib.Path(args.title_text)) else ""
cta_txt    = clean_text(pathlib.Path(args.cta_text).read_text(encoding="utf-8"))   if exists_nonempty(pathlib.Path(args.cta_text))   else ""

title_lines = wrap_by_words(title_txt, args.title_max_words) if (t1_title>t0_title and title_txt) else []
cta_lines   = wrap_by_words(cta_txt,   args.cta_max_words)   if (t1_cta>t0_cta   and cta_txt)   else []
story_chunks = make_story_chunks(story_raw, args.story_max_words_per_line, args.story_max_lines)

# Événements
events = []

# Histoire : répartition uniforme + anti-dérive
if story_chunks and (t1_story > t0_story):
    per = (t1_story - t0_story) / max(1, len(story_chunks))
    t = t0_story
    for ch in story_chunks:
        s = t
        e = min(t1_story, t + per)
        s_adj = max(t0_story, s + args.lead)
        e_adj = min(t1_story, e - args.shrink)
        if e_adj <= s_adj: e_adj = min(t1_story, s_adj + 0.08)
        events.append(("TikTok", s_adj, e_adj, ch))
        t = e

# Titre
if (t1_title > t0_title) and title_lines:
    title_text_joined = "\\N".join(title_lines)
    s_adj = max(t0_title, t0_title + args.lead)
    e_adj = min(t1_title, t1_title - args.shrink)
    if e_adj <= s_adj: e_adj = min(t1_title, s_adj + 0.08)
    events.insert(0, ("Title", s_adj, e_adj, title_text_joined))

# CTA
if (t1_cta > t0_cta) and cta_lines:
    cta_text_joined = "\\N".join(cta_lines)
    s_adj = max(t0_cta, t0_cta + args.lead)
    e_adj = min(t1_cta, t1_cta - args.shrink)
    if e_adj <= s_adj: e_adj = min(t1_cta, s_adj + 0.08)
    events.append(("CTA", s_adj, e_adj, cta_text_joined))

# Styles
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

with pathlib.Path(args.out).open("w", encoding="utf-8") as f:
    f.write(hdr)
    for style, s, e, txt in events:
        f.write(f"Dialogue: 0,{to_ass_ts(s)},{to_ass_ts(e)},{style},,0,0,0,,{txt}\n")

print(f"[build_ass] écrit: {args.out} (durée totale ~ {max(t1_title,t1_story,t1_cta):.2f}s)")