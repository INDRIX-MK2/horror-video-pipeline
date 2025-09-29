#!/usr/bin/env python3
import argparse, pathlib, subprocess, sys, shlex

ap = argparse.ArgumentParser(description="Render final TikTok with effects + ASS")
ap.add_argument("--video", required=True)
ap.add_argument("--audio", required=True)
ap.add_argument("--subs",  required=True)
ap.add_argument("--output", required=True)
args = ap.parse_args()

video = pathlib.Path(args.video)
audio = pathlib.Path(args.audio)
subs  = pathlib.Path(args.subs)
out   = pathlib.Path(args.output)
out.parent.mkdir(parents=True, exist_ok=True)

if not video.exists(): print(f"[render_final] vidéo manquante {video}", file=sys.stderr); sys.exit(1)
if not audio.exists(): print(f"[render_final] audio manquant {audio}", file=sys.stderr); sys.exit(1)
if not subs.exists():  print(f"[render_final] sous-titres manquants {subs}", file=sys.stderr); sys.exit(1)

# Filtre vidéo (léger mouvement + mise à l’échelle + net + léger contraste) + sous-titres
vf = (
    "setpts=PTS-STARTPTS,"
    "scale=1200:2133:force_original_aspect_ratio=increase,"
    "rotate=0.005*sin(2*PI*t):fillcolor=black,"
    "crop=1080:1920,"
    "unsharp=5:5:0.5:5:5:0.0,"
    "eq=contrast=1.05:brightness=0.02,"
    "fps=30"
)
fc = f"[0:v]{vf}[v0];[1:a]asetpts=PTS-STARTPTS[a0];[v0]subtitles={shlex.quote(str(subs))}[v]"

cmd = [
    "ffmpeg","-nostdin","-y",
    "-i",str(video),
    "-i",str(audio),
    "-filter_complex",fc,
    "-map","[v]","-map","[a0]",
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
