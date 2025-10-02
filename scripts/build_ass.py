#!/usr/bin/env python3
import sys, argparse, pathlib, subprocess, re, json

def ffprobe_dur(p: pathlib.Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error","-show_entries","format=duration",
            "-of","default=nk=1:nw=1", str(p)
        ], text=True).strip()
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

def clean_text(s: str) -> str:
    # on enlève crochets/didascalies et normalise espaces
    s = re.sub(r"\[[^\]]+\]", " ", s)
    s = re.sub(r"\([^)]+\)", " ", s)
    s = s.replace("\\", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def split_words_lines(text: str, max_words_per_line: int, max_lines: int):
    words = text.split()
    if not words:
        return []
    lines, buf = [], []
    for w in words:
        buf.append(w)
        if len(buf) >= max_words_per_line:
            lines.append(" ".join(buf)); buf=[]
            if len(lines) >= max_lines:
                # on continue la ligne en cours dans la dernière
                if words.index(w) < len(words)-1 and buf:
                    lines[-1] += " " + " ".join(buf)
                buf=[]
                break
    if buf:
        lines.append(" ".join(buf))
    # coupe proprement à max_lines
    return lines[:max_lines]

ap = argparse.ArgumentParser(description="Build ASS (title -> gap -> story -> gap -> cta), centered, yellow")
ap.add_argument("--transcript",  required=True, help="story/story.txt")
ap.add_argument("--audio",       required=True, help="audio/voice.wav (total)")
ap.add_argument("--out",         default="subs/captions.ass")

ap.add_argument("--title-text",  required=True, help="story/title.txt")
ap.add_argument("--cta-text",    required=True, help="story/cta.txt")
ap.add_argument("--title-audio", required=True, help="audio/title.wav")
ap.add_argument("--story-audio", required=True, help="audio/story.wav")
ap.add_argument("--cta-audio",   required=True, help="audio/cta.wav")

ap.add_argument("--title-gap-after", type=float, default=1.0)
ap.add_argument("--gap-before-cta",  type=float, default=1.0)

# Style global (modifiable via env / workflow)
ap.add_argument("--font", default="Arial")
ap.add_argument("--size", type=int, default=80)
ap.add_argument("--colour", default="&H00FFFF00")         # jaune
ap.add_argument("--outline-colour", default="&H00000000") # noir
ap.add_argument("--back-colour", default="&H40000000")
ap.add_argument("--outline", type=int, default=3)
ap.add_argument("--shadow", type=int, default=2)
ap.add_argument("--align",  type=int, default=5)
ap.add_argument("--marginv", type=int, default=200)

# Story layout & timing
ap.add_argument("--story-max-words", type=int, default=4)  # max 4 mots / ligne
ap.add_argument("--story-max-lines", type=int, default=3)  # 2~3 lignes
ap.add_argument("--lead",  type=float, default=0.0)        # avance sous-titres (s) (anti-lag +/-)
ap.add_argument("--speed", type=float, default=1.0)        # étirement global (1.0 = exact)

args = ap.parse_args()

t_title = pathlib.Path(args.title_text).read_text(encoding="utf-8").strip()
t_story = pathlib.Path(args.transcript).read_text(encoding="utf-8").strip()
t_cta   = pathlib.Path(args.cta_text).read_text(encoding="utf-8").strip()

t_title = clean_text(t_title)
t_story = clean_text(t_story)
t_cta   = clean_text(t_cta)

pa_title = pathlib.Path(args.title_audio)
pa_story = pathlib.Path(args.story_audio)
pa_cta   = pathlib.Path(args.cta_audio)

d_title = ffprobe_dur(pa_title)
d_story = ffprobe_dur(pa_story)
d_cta   = ffprobe_dur(pa_cta)

if d_title <= 0 or d_story <= 0 or d_cta <= 0:
    print("[build_ass] ERREUR: durations audio invalides", file=sys.stderr)
    sys.exit(2)

# Timeline
t0 = 0.0
t1 = t0 + d_title
t1 += max(0.0, args.title_gap_after)

s0 = t1
s1 = s0 + d_story

c0 = s1 + max(0.0, args.gap_before_cta)
c1 = c0 + d_cta

# STYLE ASS
hdr = (
    "[Script Info]\n"
    "ScriptType: v4.00+\n"
    "PlayResX: 1080\n"
    "PlayResY: 1920\n"
    "WrapStyle: 2\n"
    "ScaledBorderAndShadow: yes\n"
    "YCbCr Matrix: TV.709\n\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
    "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
    "Alignment, MarginL, MarginR, MarginV, Encoding\n"
    f"Style: TikTok,{args.font},{args.size},{args.colour},&H00000000,{args.outline_colour},{args.back_colour},"
    "0,0,0,0,100,100,0,0,1," f"{args.outline},{args.shadow},{args.align},40,40,{args.marginv},1\n\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
)

opath = pathlib.Path(args.out)
opath.parent.mkdir(parents=True, exist_ok=True)

def esc_ass(s: str) -> str:
    # Assainit les caractères spéciaux pour champ Text
    s = s.replace("{","(").replace("}",")")
    s = s.replace("\n"," ").replace("\r"," ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

events = []

# Title (sur 1–2 lignes max 4 mots/ligne, centré)
title_lines = split_words_lines(t_title, max_words_per_line=4, max_lines=2)
if not title_lines:
    title_lines = [t_title]
title_text = "\\N".join(esc_ass(l) for l in title_lines)
events.append((t0 + args.lead, t1 + args.lead, title_text))

# Story (chunks uniformes sur toute la durée)
# On casse le transcript en blocs de 2–3 lignes, 4 mots/ligne (env)
story_words = t_story.split()
# construire des chunks (groupes) en ~ 2 lignes max_lines par chunk
chunk_lines, line_buf, lines = [], [], []
for w in story_words:
    line_buf.append(w)
    if len(line_buf) >= args.story_max_words:
        lines.append(" ".join(line_buf)); line_buf=[]
if line_buf:
    lines.append(" ".join(line_buf))
# regrouper N lignes par événement (max_lines)
for i in range(0, len(lines), args.story_max_lines):
    grp = lines[i:i+args.story_max_lines]
    chunk_lines.append("\\N".join(esc_ass(x) for x in grp))

n = max(1, len(chunk_lines))
per = (d_story / n) * (1.0/args.speed)
t = s0
for txt in chunk_lines:
    s = t
    e = 
