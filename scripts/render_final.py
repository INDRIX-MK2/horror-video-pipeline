#!/usr/bin/env python3
import argparse
import subprocess
import pathlib
import sys
import shlex
import json

def ffprobe_duration(p: pathlib.Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error",
            "-show_entries","format=duration",
            "-of","json", str(p)
        ]).decode("utf-8","ignore")
        j = json.loads(out)
        return float(j.get("format", {}).get("duration", 0.0))
    except Exception:
        return 0.0

# ==========================
#  Configuration et parsing
# ==========================
ap = argparse.ArgumentParser(description="Assemble final TikTok horror video with effects")
ap.add_argument("--video", required=True, help="Chemin de la vidéo fusionnée (merged.mp4)")
ap.add_argument("--audio", required=True, help="Chemin de l'audio narratif (voice.wav)")
ap.add_argument("--subs", required=True, help="Chemin des sous-titres .ass générés")
ap.add_argument("--output", required=True, help="Fichier de sortie final")
ap.add_argument("--fps", type=int, default=30)
ap.add_argument("--crf", type=int, default=18)
ap.add_argument("--preset", default="medium")
args = ap.parse_args()

video = pathlib.Path(args.video)
audio = pathlib.Path(args.audio)
subs = pathlib.Path(args.subs)
output = pathlib.Path(args.output)

# ==========================
#  Vérifications de sécurité
# ==========================
if not video.exists() or video.stat().st_size == 0:
    print(f"[render_final] ERREUR: vidéo manquante/vide -> {video}", file=sys.stderr)
    sys.exit(1)
if not audio.exists() or audio.stat().st_size == 0:
    print(f"[render_final] ERREUR: audio manquant/vide -> {audio}", file=sys.stderr)
    sys.exit(1)
if not subs.exists() or subs.stat().st_size == 0:
    print(f"[render_final] ERREUR: sous-titres manquants/vides -> {subs}", file=sys.stderr)
    sys.exit(1)

output.parent.mkdir(parents=True, exist_ok=True)

# ==========================
#  Durée audio et fade
# ==========================
a_dur = ffprobe_duration(audio)
if a_dur <= 0.0:
    print("[render_final] ERREUR: durée audio invalide (ffprobe).", file=sys.stderr)
    sys.exit(1)

fade_in = 0.8
fade_out = 0.8
fade_out_start = max(0.0, a_dur - fade_out)

# ==========================
#  Construction des filtres FFmpeg
# ==========================
# Normalisation portrait + petit “handheld” + grading léger
base_chain = (
    "scale=1080:-2:force_original_aspect_ratio=decrease,"
    "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,"
    "rotate=0.003*sin(2*PI*t*0.5):ow=iw:oh=ih,"
    "vibrance=0.02,"
    "unsharp=5:5:0.5:5:5:0.0,"
    f"fps={args.fps}"
)

# Fades (début/fin) sur la durée connue
fade_chain = f"fade=t=in:st=0:d={fade_in},fade=t=out:st={fade_out_start:.3f}:d={fade_out}"

# Sous-titres .ass (toujours en dernier pour ne pas flouter/altérer le rendu du texte)
subs_filter = f"subtitles={shlex.quote(str(subs))}"

# Chaîne finale : entrée vidéo -> base_chain -> fades -> subs
# On utilise filter_complex pour chaîner proprement et mapper la sortie nommée.
filter_complex = f"[0:v]{base_chain},{fade_chain}[v1];[v1]{subs_filter}[vout]"

# ==========================
#  Commande FFmpeg finale
# ==========================
cmd = [
    "ffmpeg", "-nostdin", "-y",
    "-i", str(video),
    "-i", str(audio),
    # On borne la durée au temps de l'audio
    "-t", f"{a_dur:.3f}",
    "-filter_complex", filter_complex,
    "-map", "[vout]",
    "-map", "1:a:0",
    "-c:v", "libx264",
    "-preset", args.preset,
    "-crf", str(args.crf),
    "-pix_fmt", "yuv420p",
    "-c:a", "aac",
    "-b:a", "192k",
    "-shortest",
    str(output)
]

print("[render_final] Exécution de FFmpeg…")
print(" ".join(shlex.quote(c) for c in cmd))

try:
    subprocess.run(cmd, check=True)
except subprocess.CalledProcessError as e:
    print(f"[render_final] ERREUR FFmpeg: {e}", file=sys.stderr)
    sys.exit(1)

print(f"[render_final] Vidéo finale générée avec succès -> {output}")