#!/usr/bin/env python3
import sys, argparse, pathlib, subprocess, re, json

ap = argparse.ArgumentParser(description="Build ASS subtitles for story, with optional start offset")
ap.add_argument("--transcript", required=True)
ap.add_argument("--audio", required=True)
ap.add_argument("--out", default="subs/captions.ass")
ap.add_argument("--font", default="Arial")
ap.add_argument("--size", type=int, default=60)
ap.add_argument("--timeline", help="audio/timeline.json (pour décaler le début aux/à title+gap)")
ap.add_argument("--offset", type=float, default=None, help="force offset (sec) si fourni")
ap.add_argument("--words-per-line", type=int, default=4)
ap.add_argument("--max-lines", type=int, default=3)
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
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error","-show_entries","format=duration",
            "-of","default=nk=1:nw=1", str(p)
        ]).decode("utf-8","ignore").strip()
        return float(out)
    except Exception:
        return 0.0

offset = 0.0
if args.offset is not None:
    offset = max(0.0, float(args.offset))
elif args.timeline:
    j = pathlib.Path(args.timeline)
    if j.exists() and j.stat().st_size:
        try:
            tl = json.loads(j.read_text(encoding="utf-8"))
            offset = float(tl.get("title",0.0)) + float(tl.get("gap",0.0))
        except Exception:
            offset = 0.0

audio_dur = max(0.01, dur_audio(apath))
raw = tpath.read_text(encoding="utf-8")

# Nettoyage léger: retire crochets/parenthèses (didascalies résiduelles)
raw = re.sub(r"\[[^\]]+\]", "", raw)
raw = re.sub(r"\([^)]+\)", "", raw)

# Split en phrases, puis re-wrap en lignes de 4 mots, max 2-3 lignes
sentences = re.split(r"(?<=[\.\!\?…])\s+", raw.strip())
sentences = [s.strip() for s in sentences if s.strip()]

def wrap_words(text, wpl=4, max_lines=3):
    words = text.split()
    if not words: return [""]
    lines, buf = [], []
    for w in words:
        buf.append(w)
        if len(buf) >= wpl:
            lines.append(" ".join(buf)); buf=[]
            if len(lines) >= max_lines:  # si on dépasse, on pousse le reste sur la dernière ligne
                break
    if buf:
        if len(lines) < max_lines:
            lines.append(" ".join(buf))
        else:
            lines[-1] += " " + " ".join(buf)
    return lines

# On répartit le temps restant (audio_dur - offset) sur les phrases
usable = max(0.01, audio_dur - offset)
n = max(1, len(sentences))
per = usable / n

events = []
t = offset
for s in sentences:
    s_lines = wrap_words(s, wpl=args.words-per-line if hasattr(args,'words-per-line') else args.words_per_line, max_lines=args.max_lines)
    txt = r"\N".join(s_lines)  # multi-lignes ASS
    start = t
    end = min(audio_dur, t + per)
    events.append((start, end, txt))
    t = end

def to_ass_ts(sec):
    if sec < 0: sec = 0
    h = int(sec // 3600); m = int((sec % 3600) // 60); s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

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

with opath.open("w", encoding="utf-8") as f:
    f.write(hdr)
    for s,e,txt in events:
        f.write(f"Dialogue: 0,{to_ass_ts(s)},{to_ass_ts(e)},TikTok,,0,0,0,,{txt}\n")

print(f"[build_ass] écrit: {opath} (offset={offset:.2f}s, audio={audio_dur:.2f}s)")