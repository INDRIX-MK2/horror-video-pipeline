#!/usr/bin/env python3
import argparse, pathlib, sys, re, subprocess, shlex, json

def ffprobe_dur(path: pathlib.Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error","-show_entries","format=duration","-of","default=nk=1:nw=1", str(path)
        ]).decode("utf-8","ignore").strip()
        return float(out)
    except Exception:
        return 0.0

def to_ts(sec: float) -> str:
    if sec < 0: sec = 0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

def cleanup_text(t: str) -> str:
    t = re.sub(r"\[[^\]]+\]", "", t)
    t = re.sub(r"\([^)]+\)", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def break_lines(text: str, max_words: int, max_lines: int):
    words = text.split()
    chunks, buf = [], []
    for w in words:
        buf.append(w)
        if len(buf) >= max_words:
            chunks.append(" ".join(buf)); buf=[]
    if buf: chunks.append(" ".join(buf))
    if not chunks: return []
    # replacer en lignes max_lines (jointure si besoin)
    out = []
    group = []
    for ch in chunks:
        group.append(ch)
        if len(group) == max_lines:
            out.append("\\N".join(group)); group=[]
    if group:
        out.append("\\N".join(group))
    return out

ap = argparse.ArgumentParser(description="Build ASS with Title + Story + CTA")
ap.add_argument("--transcript", required=True, help="story/story.txt (histoire)")
ap.add_argument("--audio", required=True, help="audio/voice.wav (final concat)")
ap.add_argument("--out", default="subs/captions.ass")

# paramètres story (style TikTok)
ap.add_argument("--font", default="Arial")
ap.add_argument("--size", type=int, default=60)
ap.add_argument("--colour", default="&H00FFFFFF")
ap.add_argument("--outline-colour", default="&H00000000")
ap.add_argument("--back-colour", default="&H64000000")
ap.add_argument("--outline", type=int, default=3)
ap.add_argument("--shadow", type=int, default=2)
ap.add_argument("--align", type=int, default=5)
ap.add_argument("--marginv", type=int, default=200)
ap.add_argument("--max-words", type=int, default=4)
ap.add_argument("--max-lines", type=int, default=2)

# Title
ap.add_argument("--title-text", required=True, help="story/title.txt")
ap.add_argument("--title-audio", required=True, help="audio/title.wav")
ap.add_argument("--title-gap-after", type=float, default=1.0)
ap.add_argument("--title-size", type=int, default=84)
ap.add_argument("--title-colour", default="&H00FFFF00")
ap.add_argument("--title-align", type=int, default=5)
ap.add_argument("--title-marginv", type=int, default=700)
ap.add_argument("--title-max-words", type=int, default=4)

# CTA
ap.add_argument("--cta-text", required=True, help="story/cta.txt")
ap.add_argument("--cta-audio", required=True, help="audio/cta.wav")
ap.add_argument("--gap-before-cta", type=float, default=1.0)
ap.add_argument("--cta-size", type=int, default=72)
ap.add_argument("--cta-colour", default="&H00FFFF00")
ap.add_argument("--cta-align", type=int, default=5)
ap.add_argument("--cta-marginv", type=int, default=700)
ap.add_argument("--cta-max-words", type=int, default=4)

# audio narration seule (pour caler la durée des sous-titres Story)
ap.add_argument("--story-audio", default="audio/story.wav")

args = ap.parse_args()

t_story = pathlib.Path(args.transcript).read_text(encoding="utf-8").strip()
t_title = pathlib.Path(args.title-text if hasattr(args, "title-text") else args.title_text)  # guard pylance
# corrige l’accès (pylance n’aime pas “-”); on passe par __dict__
t_title = pathlib.Path(args.__dict__["title_text"]).read_text(encoding="utf-8").strip()
t_cta   = pathlib.Path(args.__dict__["cta_text"]).read_text(encoding="utf-8").strip()

p_title_a = pathlib.Path(args.__dict__["title_audio"])
p_story_a = pathlib.Path(args.story_audio)
p_cta_a   = pathlib.Path(args.__dict__["cta_audio"])

if not p_title_a.exists() or not p_story_a.exists() or not p_cta_a.exists():
    print("Audios segmentés manquants (title/story/cta).", file=sys.stderr)
    sys.exit(1)

# durations
d_title = ffprobe_dur(p_title_a)
d_story = ffprobe_dur(p_story_a)
d_cta   = ffprobe_dur(p_cta_a)

# place des blocs
t0 = 0.0
t1 = t0 + d_title
t2 = t1 + max(0.1, args.title_gap_after)
t3 = t2 + d_story
t4 = t3 + max(0.1, args.gap_before_cta)
t5 = t4 + d_cta

# Prépare les lignes
title_lines = break_lines(cleanup_text(t_title), args.title_max_words, 2) or [" "]
story_lines_words = cleanup_text(t_story).split()

# fabriquer les lignes story selon max-words / max-lines
story_chunks, buf = [], []
for w in story_lines_words:
    buf.append(w)
    if len(buf) >= args.max_words:
        story_chunks.append(" ".join(buf)); buf=[]
if buf: story_chunks.append(" ".join(buf))
# Regrouper en lignes avec \N
story_lines = []
group=[]
for ch in story_chunks:
    group.append(ch)
    if len(group) == args.max_lines:
        story_lines.append("\\N".join(group)); group=[]
if group: story_lines.append("\\N".join(group))

cta_lines = break_lines(cleanup_text(t_cta), args.cta_max_words, 2) or [" "]

# Répartition temporelle : uniforme dans chaque bloc
def spread(start, end, lines):
    if not lines: return []
    dur = max(0.01, end - start)
    step = dur / len(lines)
    out=[]
    t = start
    for ln in lines:
        s = t
        e = min(end, t + step)
        out.append((s,e,ln))
        t = e
    return out

events = []
events += [("Title",)+ev for ev in spread(t0, t1, title_lines)]
events += [("TikTok",)+ev for ev in spread(t2, t3, story_lines)]
events += [("CTA",  )+ev for ev in spread(t4, t5, cta_lines)]

# Header ASS avec 3 styles
hdr = (
    "[Script Info]\n"
    "ScriptType: v4.00+\n"
    "PlayResX: 1080\n"
    "PlayResY: 1920\n"
    "WrapStyle: 2\n"
    "ScaledBorderAndShadow: yes\n"
    "YCbCr Matrix: TV.709\n"
    "\n[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
    "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
    "MarginL, MarginR, MarginV, Encoding\n"
    f"Style: TikTok,{args.font},{args.size},{args.colour},{'&H00000000'},{args.outline_colour},{args.back_colour},"
    "0,0,0,0,100,100,0,0,1,"
    f"{args.outline},{args.shadow},{args.align},40,40,{args.marginv},1\n"
    f"Style: Title,{args.font},{args.title_size},{args.title_colour},{'&H00000000'},{'&H00000000'},{'&H64000000'},"
    "0,0,0,0,100,100,0,0,1,4,2,"
    f"{args.title_align},40,40,{args.title_marginv},1\n"
    f"Style: CTA,{args.font},{args.cta_size},{args.cta_colour},{'&H00000000'},{'&H00000000'},{'&H64000000'},"
    "0,0,0,0,100,100,0,0,1,4,2,"
    f"{args.cta_align},40,40,{args.cta_marginv},1\n"
    "\n[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
)

opath = pathlib.Path(args.out)
opath.parent.mkdir(parents=True, exist_ok=True)
with opath.open("w", encoding="utf-8") as f:
    f.write(hdr)
    for style, s, e, txt in events:
        f.write(f"Dialogue: 0,{to_ts(s)},{to_ts(e)},{style},,0,0,0,,{txt}\n")

# Sanity
has_dialogue = any(line.startswith("Dialogue:") for line in opath.read_text(encoding="utf-8").splitlines())
if not has_dialogue:
    print("[build_ass] Aucun Dialogue:, vérifier entrées.", file=sys.stderr); sys.exit(2)

print(f"[build_ass] OK -> {opath}")
