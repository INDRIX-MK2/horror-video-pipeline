#!/usr/bin/env python3
import argparse, pathlib, subprocess, sys

ap = argparse.ArgumentParser()
ap.add_argument("--video", required=True)
ap.add_argument("--audio", required=True)
ap.add_argument("--ass", required=True)
ap.add_argument("--output", required=True)
args = ap.parse_args()

v = pathlib.Path(args.video)
a = pathlib.Path(args.audio)
ass = pathlib.Path(args.ass)
o = pathlib.Path(args.output)
o.parent.mkdir(parents=True, exist_ok=True)

for p in (v,a,ass):
    if not p.exists() or not p.stat().st_size:
        print(f"Manquant/vide: {p}", file=sys.stderr); sys.exit(1)

# Sous-titres ASS en overlay, -shortest = caler la vidéo sur l’audio si besoin
cmd = [
    "ffmpeg","-nostdin","-y",
    "-i", str(v),
    "-i", str(a),
    "-vf", f"subtitles={ass.as_posix()}",
    "-map","0:v:0","-map","1:a:0",
    "-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",
    "-c:a","aac","-b:a","192k",
    "-shortest",
    str(o)
]
subprocess.run(cmd, check=True)
print(f"[render] écrit: {o}")