#!/usr/bin/env python3
import argparse, subprocess, pathlib, sys, shlex

# ==========================
#  CLI
# ==========================
ap = argparse.ArgumentParser(description="Assemble la vidéo finale (effets + sous-titres)")
ap.add_argument("--video",  required=True, help="Chemin de la vidéo fusionnée (merged.mp4)")
ap.add_argument("--audio",  required=True, help="Chemin de l'audio narratif (voice.wav)")
ap.add_argument("--subs",   required=True, help="Chemin des sous-titres .ass")
ap.add_argument("--output", required=True, help="Fichier mp4 de sortie")
args = ap.parse_args()

video  = pathlib.Path(args.video)
audio  = pathlib.Path(args.audio)
subs   = pathlib.Path(args.subs)
output = pathlib.Path(args.output)

# ==========================
#  Vérifs
# ==========================
if not video.exists():
    print(f"[render_final] ERREUR: vidéo manquante -> {video}", file=sys.stderr); sys.exit(1)
if not audio.exists():
    print(f"[render_final] ERREUR: audio manquant -> {audio}", file=sys.stderr); sys.exit(1)
if not subs.exists():
    print(f"[render_final] ERREUR: sous-titres manquants -> {subs}", file=sys.stderr); sys.exit(1)

output.parent.mkdir(parents=True, exist_ok=True)

# ==========================
#  Filtre FFmpeg
#  - RESET PTS vidéo + audio (clé pour la sync)
#  - Légers effets (contrast, sharpen, shake)
#  - Fades in/out courts
#  - Incruste des sous-titres .ass
# ==========================
video_chain = (
    "setpts=PTS-STARTPTS,"                      # remet la vidéo à t=0
    "eq=contrast=1.05:brightness=0.02,"
    "scale=1080:1920:force_original_aspect_ratio=increase,"
    "crop=1080:1920,"
    "unsharp=5:5:0.5:5:5:0.0,"
    "fps=30,"
    "shake=1:1:0.5:0.5:seed=42,"
    "fade=t=in:st=0:d=0.6,fade=t=out:st=duration-0.6:d=0.6"
)

audio_chain = "asetpts=PTS-STARTPTS"            # remet l’audio à t=0
subtitles_filter = f"subtitles={shlex.quote(str(subs))}"

filter_complex = (
    f"[0:v]{video_chain}[v0];"
    f"[1:a]{audio_chain}[a0];"
    f"[v0]{subtitles_filter}[v]"
)

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
    print(f"[render_final] ERREUR FFmpeg: {e}", file=sys.stderr); sys.exit(1)

print(f"[render_final] OK -> {output}")