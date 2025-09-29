#!/usr/bin/env python3
import argparse
import subprocess
import pathlib
import sys
import shlex

def ffprobe_duration(path: pathlib.Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=nk=1:nw=1",
            str(path)
        ]).decode("utf-8", "ignore").strip()
        return float(out)
    except Exception:
        return 0.0

def build_filter(subs_path: pathlib.Path, vdur: float) -> str:
    # Chaîne vidéo (stabilité + lisibilité)
    vf_chain = (
        "setpts=PTS-STARTPTS,"
        "scale=1200:2133:force_original_aspect_ratio=increase,"
        "rotate=0.005*sin(2*PI*t):fillcolor=black,"
        "crop=1080:1920,"
        "unsharp=5:5:0.5:5:5:0.0,"
        "eq=contrast=1.05:brightness=0.02,"
        "fps=30"
    )

    # Fade in/out global sur la vidéo (compute st de fade out côté Python)
    # On n’essaie pas d’utiliser 'duration' côté ffmpeg (non valide).
    fade_in_d = 0.6
    vf_chain += f",fade=t=in:st=0:d={fade_in_d:.3f}"

    fade_out_d = 0.6
    if vdur > (fade_in_d + fade_out_d + 0.2):
        st_out = max(0.0, vdur - fade_out_d)
        vf_chain += f",fade=t=out:st={st_out:.3f}:d={fade_out_d:.3f}"

    # Subtitles en dernier dans la chaîne vidéo
    subs_arg = subs_path.as_posix()
    # IMPORTANT : le filtre subtitles s’écrit sans guillemets quand le chemin n’a pas d’espaces/':'.
    # Si ton chemin contient des espaces, préfère déplacer le repo sur un chemin sans espaces.
    filter_complex = f"[0:v]{vf_chain}[v0];[v0]subtitles={subs_arg}[v];[1:a]asetpts=PTS-STARTPTS[a]"
    return filter_complex

def main():
    ap = argparse.ArgumentParser(description="Assemble final TikTok horror video with effects")
    ap.add_argument("--video", required=True, help="Chemin de la vidéo fusionnée (merged.mp4)")
    ap.add_argument("--audio", required=True, help="Chemin de l'audio narratif (voice.wav)")
    ap.add_argument("--subs",  required=True, help="Chemin des sous-titres .ass")
    ap.add_argument("--output", required=True, help="Fichier de sortie final")
    args = ap.parse_args()

    video = pathlib.Path(args.video)
    audio = pathlib.Path(args.audio)
    subs  = pathlib.Path(args.subs)
    output = pathlib.Path(args.output)

    if not video.exists():
        print(f"[render_final] ERREUR: vidéo manquante -> {video}", file=sys.stderr)
        sys.exit(1)
    if not audio.exists():
        print(f"[render_final] ERREUR: audio manquant -> {audio}", file=sys.stderr)
        sys.exit(1)
    if not subs.exists():
        print(f"[render_final] ERREUR: sous-titres manquants -> {subs}", file=sys.stderr)
        sys.exit(1)

    # Vérifier qu'il y a au moins un 'Dialogue:' dans le .ass
    try:
        txt = subs.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        txt = ""
    if "Dialogue:" not in txt:
        print(f"[render_final] ERREUR: {subs} ne contient aucun 'Dialogue:' => rien à incruster.", file=sys.stderr)
        sys.exit(2)

    output.parent.mkdir(parents=True, exist_ok=True)

    vdur = ffprobe_duration(video)
    acmd = [
        "ffmpeg", "-nostdin", "-y",
        "-i", str(video),
        "-i", str(audio),
        "-filter_complex", build_filter(subs, vdur),
        "-map", "[v]", "-map", "[a]",
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
    print(" ".join(shlex.quote(c) for c in acmd))

    try:
        subprocess.run(acmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[render_final] ERREUR FFmpeg: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[render_final] Vidéo finale générée -> {output}")

if __name__ == "__main__":
    main()
