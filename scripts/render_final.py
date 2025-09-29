#!/usr/bin/env python3
import argparse, subprocess, pathlib, sys, shlex

ap = argparse.ArgumentParser(description="Assemble la vidéo finale avec effets légers + sous-titres .ass")
ap.add_argument("--video", required=True, help="merged.mp4")
ap.add_argument("--audio", required=True, help="voice.wav (chaîne titre + pause + histoire + pause + cta)")
ap.add_argument("--subs",  required=True, help="subs/captions.ass")
ap.add_argument("--output", required=True, help="final_video/final_horror.mp4")
args = ap.parse_args()

video = pathlib.Path(args.video)
audio = pathlib.Path(args.audio)
subs  = pathlib.Path(args.subs)
out   = pathlib.Path(args.output)

for p, label in [(video,"vidéo"),(audio,"audio"),(subs,"sous-titres")]:
    if not p.exists():
        print(f"[render_final] ERREUR: {label} manquant -> {p}", file=sys.stderr); sys.exit(1)

out.parent.mkdir(parents=True, exist_ok=True)

# Chaîne d'effets vidéo (pas de drawtext ; les titres/CTA viennent du .ass)
vf = (
    "setpts=PTS-STARTPTS,"
    "scale=1200:2133:force_original_aspect_ratio=increase,"
    "rotate=0.005*sin(2*PI*t):fillcolor=black,"
    "crop=1080:1920,"
    "unsharp=5:5:0.5:5:5:0.0,"
    "eq=contrast=1.05:brightness=0.02,"
    "fps=30,"
    f"subtitles={shlex.quote(str(subs))}"
)

cmd = [
    "ffmpeg","-nostdin","-y",
    "-i", str(video),
    "-i", str(audio),
    "-filter_complex", f"[0:v]{vf}[v];[1:a]asetpts=PTS-STARTPTS[a]",
    "-map","[v]","-map","[a]",
    "-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",
    "-c:a","aac","-b:a","192k",
    "-movflags","+faststart",
    "-shortest",
    str(out)
]

print("[render_final] Exécution FFmpeg…")
print(" ".join(shlex.quote(x) for x in cmd))
try:
    subprocess.run(cmd, check=True)
except subprocess.CalledProcessError as e:
    print(f"[render_final] ERREUR FFmpeg: {e}", file=sys.stderr); sys.exit(1)

print(f"[render_final] OK -> {out}")