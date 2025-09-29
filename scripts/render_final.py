#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import subprocess
import pathlib
import sys
import shlex
import re

def count_ass_dialogues(ass_path: pathlib.Path) -> int:
    try:
        txt = ass_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return 0
    # Compte les lignes d'événements
    return sum(1 for ln in txt.splitlines() if ln.strip().lower().startswith("dialogue:"))

ap = argparse.ArgumentParser(description="Assemble final TikTok horror video with effects + hardcoded ASS subtitles")
ap.add_argument("--video", required=True, help="Chemin de la vidéo fusionnée (merged.mp4)")
ap.add_argument("--audio", required=True, help="Chemin de l'audio narratif (voice.wav)")
ap.add_argument("--subs",  required=True, help="Chemin des sous-titres .ass générés (ex: subs/captions.ass)")
ap.add_argument("--output", required=True, help="Fichier de sortie final (ex: final_video/final_horror.mp4)")
args = ap.parse_args()

video = pathlib.Path(args.video)
audio = pathlib.Path(args.audio)
subs  = pathlib.Path(args.subs)
output = pathlib.Path(args.output)

# ---------------- Vérifs de sécurité ----------------
if not video.exists() or video.stat().st_size == 0:
    print(f"[render_final] ERREUR: vidéo manquante ou vide -> {video}", file=sys.stderr)
    sys.exit(1)

if not audio.exists() or audio.stat().st_size == 0:
    print(f"[render_final] ERREUR: audio manquant ou vide -> {audio}", file=sys.stderr)
    sys.exit(1)

if not subs.exists() or subs.stat().st_size == 0:
    print(f"[render_final] ERREUR: sous-titres .ass manquants ou vides -> {subs}", file=sys.stderr)
    sys.exit(1)

dialogues = count_ass_dialogues(subs)
if dialogues == 0:
    print(f"[render_final] ERREUR: {subs} ne contient aucun évènement 'Dialogue:' => rien à incruster.", file=sys.stderr)
    sys.exit(2)

output.parent.mkdir(parents=True, exist_ok=True)

# ---------------- Filtres vidéo/audio ----------------
# Effets légers et stables (pas de fade-out dépendant de 'duration')
vf_chain = (
    "setpts=PTS-STARTPTS,"
    "scale=1200:2133:force_original_aspect_ratio=increase,"
    "rotate=0.003*sin(2*PI*t):fillcolor=black,"
    "crop=1080:1920,"
    "unsharp=5:5:0.5:5:5:0.0,"
    "eq=contrast=1.05:brightness=0.02,"
    "fps=30"
)

# On passe par filter_complex pour incruster les sous-titres .ass
# IMPORTANT: on utilise la syntaxe 'subtitles=filename=...' pour éviter les soucis d'analyse.
subs_filter = f"subtitles=filename={shlex.quote(str(subs))}"

fcomplex = f"[0:v]{vf_chain}[v0];[1:a]asetpts=PTS-STARTPTS[a0];[v0]{subs_filter}[v]"

cmd = [
    "ffmpeg", "-nostdin", "-y",
    "-i", str(video),
    "-i", str(audio),
    "-filter_complex", fcomplex,
    "-map", "[v]",
    "-map", "[a0]",
    "-c:v", "libx264",
    "-preset", "medium",
    "-crf", "18",
    "-pix_fmt", "yuv420p",
    "-c:a", "aac",
    "-b:a", "192k",
    "-movflags", "+faststart",
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