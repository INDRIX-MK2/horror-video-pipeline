#!/usr/bin/env python3
import argparse, pathlib, subprocess, sys, shlex

def main():
    ap = argparse.ArgumentParser(description="Finalize TikTok video (no subtitles).")
    ap.add_argument("--video",  required=True, help="Vidéo fusionnée (depuis select_and_merge)")
    ap.add_argument("--audio",  required=True, help="Audio narratif (voice.wav)")
    ap.add_argument("--output", required=True, help="Chemin de sortie final")
    args = ap.parse_args()

    v = pathlib.Path(args.video)
    a = pathlib.Path(args.audio)
    o = pathlib.Path(args.output)
    o.parent.mkdir(parents=True, exist_ok=True)

    if not v.exists() or v.stat().st_size == 0:
        print(f"[render_final] ERREUR: vidéo manquante -> {v}", file=sys.stderr); sys.exit(1)
    if not a.exists() or a.stat().st_size == 0:
        print(f"[render_final] ERREUR: audio manquant -> {a}", file=sys.stderr); sys.exit(1)

    # Filtres finaux (pas de sous-titres ici)
    vf = (
        "setpts=PTS-STARTPTS,"
        "scale=1200:2133:force_original_aspect_ratio=increase,"
        "rotate=0.005*sin(2*PI*t):fillcolor=black,"
        "crop=1080:1920,"
        "unsharp=5:5:0.5:5:5:0.0,"
        "eq=contrast=1.05:brightness=0.02,"
        "fps=30"
    )

    cmd = [
        "ffmpeg","-nostdin","-y",
        "-i", str(v),
        "-i", str(a),
        "-filter_complex", f"[0:v]{vf}[v0];[1:a]asetpts=PTS-STARTPTS[a0]",
        "-map","[v0]","-map","[a0]",
        "-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",
        "-c:a","aac","-b:a","192k",
        "-movflags","+faststart",
        "-shortest",
        str(o)
    ]

    print("[render_final] Exécution FFmpeg…")
    print(" ".join(shlex.quote(c) for c in cmd))
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[render_final] ERREUR FFmpeg: {e}", file=sys.stderr); sys.exit(1)

    print(f"[render_final] OK -> {o}")

if __name__ == "__main__":
    main()
