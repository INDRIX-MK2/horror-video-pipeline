#!/usr/bin/env python3
import os, sys, pathlib, json, subprocess, shlex, re

voice = pathlib.Path("audio/voice.mp3")
if not voice.exists():
    print("Audio introuvable: audio/voice.mp3", file=sys.stderr)
    sys.exit(1)

story = pathlib.Path("story/story.txt")
if not story.exists():
    print("Texte introuvable: story/story.txt", file=sys.stderr)
    sys.exit(1)
text = story.read_text(encoding="utf-8").strip()

def ffprobe_duration(p: pathlib.Path) -> float:
    cmd = ["ffprobe","-v","error","-show_entries","format=duration","-of","json",str(p)]
    out = subprocess.check_output(cmd)
    j = json.loads(out.decode("utf-8"))
    return float(j["format"]["duration"])

dur = max(0.1, ffprobe_duration(voice))

# Split en phrases -> si trop long, on retombe sur paquets de ~6 mots
raw_sentences = re.split(r'(?<=[\.\!\?])\s+', text)
sentences = []
for s in raw_sentences:
    s = s.strip()
    if not s: 
        continue
    words = s.split()
    if len(words) <= 9:
        sentences.append(s)
    else:
        for i in range(0, len(words), 6):
            sentences.append(" ".join(words[i:i+6]))

n = max(1, len(sentences))
# Temps par ligne, en gardant 0.5s de marge finale (évite cut sec sur dernière ligne)
per = max(dur / n, 0.8)
# Si somme dépasse dur, on compresse légèrement
total_needed = per * n
if total_needed > dur:
    per = dur / n

def ts(sec: float) -> str:
    if sec < 0: sec = 0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"

hdr = [
"[Script Info]",
"ScriptType: v4.00+",
"PlayResX: 1080",
"PlayResY: 1920",
"ScaledBorderAndShadow: yes",
"",
"[V4+ Styles]",
"Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
"Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
"Alignment, MarginL, MarginR, MarginV, Encoding",
"Style: TikTok,Montserrat,48,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,3,0,2,50,50,100,1",
"",
"[Events]",
"Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
]

events = []
t = 0.0
for s in sentences:
    start = t
    end = min(t + per, dur)
    if end - start < 0.5:
        end = min(start + 0.5, dur)
    # Kara minimal: on garde le texte brut (pas de \k précis faute d'alignement mot-à-mot)
    # On met un léger \N pour limiter la largeur
    clean = s.replace("{", "").replace("}", "")
    wrap = re.sub(r"\s{2,}", " ", clean)
    events.append(f"Dialogue: 0,{ts(start)},{ts(end)},TikTok,,0,0,0,,{wrap}")
    t = end

out_dir = pathlib.Path("subtitles")
out_dir.mkdir(parents=True, exist_ok=True)
ass = out_dir/"captions.ass"
ass.write_text("\n".join(hdr + events) + "\n", encoding="utf-8")
print(f"OK: {ass} ({len(events)} lignes)")