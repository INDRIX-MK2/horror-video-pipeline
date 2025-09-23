#!/usr/bin/env python3
import pathlib, json, subprocess, sys, os

ROOT = pathlib.Path(__file__).resolve().parent.parent
MERGED = ROOT / "selected_media" / "merged.mp4"
ASS = ROOT / "subtitles" / "captions.ass"
WAV = ROOT / "audio" / "voice.wav"
DUR = ROOT / "audio" / "duration.json"
OUTDIR = ROOT / "final_video"
OUTDIR.mkdir(parents=True, exist_ok=True)
OUT = OUTDIR / os.environ.get("OUT_NAME","final_horror.mp4")

if not MERGED.exists(): print("merged.mp4 manquant", file=sys.stderr); sys.exit(1)
if not ASS.exists(): print("captions.ass manquant", file=sys.stderr); sys.exit(1)
if not WAV.exists(): print("voice.wav manquant", file=sys.stderr); sys.exit(1)
if not DUR.exists(): print("duration.json manquant", file=sys.stderr); sys.exit(1)

duration = float(json.loads(DUR.read_text(encoding="utf-8")).get("seconds", 0.0))
if duration <= 0.1: print("Durée audio invalide", file=sys.stderr); sys.exit(1)

# On coupe la vidéo exactement à la durée de l'audio (pas de fond noir)
cmd = [
    "ffmpeg","-nostdin","-y",
    "-i", str(MERGED),
    "-i", str(WAV),
    "-filter_complex", f"subtitles={ASS.as_posix()}",
    "-map","0:v:0","-map","1:a:0",
    "-t", f"{duration + 0.05:.2f}",
    "-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",
    "-c:a","aac","-b:a","192k",
    str(OUT)
]
subprocess.run(cmd, check=True)
print(f"Final video: {OUT}")