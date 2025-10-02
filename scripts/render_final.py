#!/usr/bin/env python3
import argparse, subprocess, pathlib, sys, shlex

ap = argparse.ArgumentParser(description="Assemble final TikTok horror video with safe filters + ASS")
ap.add_argument("--video", required=True, help="Chemin de la vidéo fusionnée (merged.mp4)")
ap.add_argument("--audio", required=True, help="Chemin de l'audio narratif (voice.wav)")
ap.add_argument("--subs",  required=True, help="Chemin des sous-titres .ass générés")
ap.add_argument("--output", required=True, help="Fichier de sortie final")
args = ap.parse_args()

video = pathlib.Path(args.video)
audio = pathlib.Path(args.audio)
subs  = pathlib.Path(args.subs)
output= pathlib.Path(args.output)

if not video.exists():
    print(f"[render_final] ERREUR: vidéo manquante -> {video}", file=sys.stderr); sys.exit(1)
if not audio.exists():
    print(f"[render_final] ERREUR: audio manquant -> {audio}", file=sys.stderr); sys.exit(1)
if not subs.exists():
    print(f"[render_final] ERREUR: sous-titres manquants -> {subs}", file=sys.stderr); sys.exit(1)

# Simple, robuste : scale/crop/eq/fps + subtitles
vf_chain = (
    "setpts=PTS-STARTPTS,"
    "scale=1200:2133:force_original_aspect_ratio=increase,"
    "crop=1080:1920,"
    "unsharp=5:5:0.5:5:5:0.0,"
    "eq=contrast=1.05:brightness=0.02,"
    "fps=30"
)
sub_filter = f"subtitles={shlex.quote(str(subs))}"

filter_complex = f"[0:v]{vf_chain}[v0];[1:a]asetpts=PTS-STARTPTS[a0];[v0]{sub_filter}[v]"

cmd = [
    "ffmpeg","-nostdin","-y",
    "-i", str(video),
    "-i", str(audio),
    "-filter_complex", filter_complex,
    "-map","[v]","-map","[a0]",
    "-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",
    "-c:a","aac","-b:a","192k",
    "-movflags","+faststart",
    "-shortest",
    str(output)
]

print("[render_final] Exécution FFmpeg…")
print(" ".join(shlex.quote(c) for c in cmd))

try:
    subprocess.run(cmd, check=True)
except subprocess.CalledProcessError as e:
    print(f"[render_final] ERREUR FFmpeg: {e}", file=sys.stderr)
    sys.exit(1)

print(f"[render_final] OK -> {output}")
