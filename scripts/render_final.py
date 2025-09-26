#!/usr/bin/env python3
import argparse, subprocess, pathlib, sys, shlex

def probe_duration(path: pathlib.Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error",
            "-show_entries","format=duration",
            "-of","default=nk=1:nw=1",
            str(path)
        ], text=True).strip()
        return max(0.0, float(out))
    except Exception:
        return 0.0

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

# ---- Vérifs
if not video.exists():
    print(f"[render_final] ERREUR: vidéo manquante -> {video}", file=sys.stderr); sys.exit(1)
if not audio.exists():
    print(f"[render_final] ERREUR: audio manquant -> {audio}", file=sys.stderr); sys.exit(1)
if not subs.exists():
    print(f"[render_final] ERREUR: sous-titres manquants -> {subs}", file=sys.stderr); sys.exit(1)
output.parent.mkdir(parents=True, exist_ok=True)

# ---- Durée vidéo pour calculer le fade-out
v_dur = probe_duration(video)
fade_len = 0.6
fade_out_start = max(0.0, v_dur - fade_len)  # nombre réel constant, accepté par FFmpeg

# ---- Chaîne vidéo 100% filtres natifs FFmpeg
# - setpts: reset PTS (sync)
# - scale de sécurité + rotate sinusoïdal très léger (simule handheld)
# - crop 1080x1920
# - unsharp + léger contraste
# - fps=30
# - fade in/out avec valeurs NUMÉRIQUES (pas d'expressions)
video_chain = (
    "setpts=PTS-STARTPTS,"
    "scale=1200:2133:force_original_aspect_ratio=increase,"
    "rotate=0.005*sin(2*PI*t):fillcolor=black,"
    "crop=1080:1920,"
    "unsharp=5:5:0.5:5:5:0.0,"
    "eq=contrast=1.05:brightness=0.02,"
    "fps=30,"
    f"fade=t=in:st=0:d={fade_len:.3f},"
    f"fade=t=out:st={fade_out_start:.3f}:d={fade_len:.3f}"
)

audio_chain = "asetpts=PTS-STARTPTS"
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