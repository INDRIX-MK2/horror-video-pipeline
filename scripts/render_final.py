#!/usr/bin/env python3
import argparse, os, shlex, subprocess, sys, pathlib

def fail(msg: str):
    print(msg, file=sys.stderr)
    sys.exit(1)

def ffprobe_duration(path: str) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error","-show_entries","format=duration",
            "-of","default=noprint_wrappers=1:nokey=1", path
        ], text=True).strip()
        return float(out) if out else 0.0
    except Exception:
        return 0.0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True, help="Fond vidéo (déjà 1080x1920 concaténé)")
    ap.add_argument("--audio", required=True, help="Voix off WAV/MP3")
    ap.add_argument("--subs",  required=False, help="Sous-titres .srt ou .ass (optionnel)")
    ap.add_argument("--output", required=True, help="Fichier de sortie MP4")
    args = ap.parse_args()

    v = args.video
    a = args.audio
    s = args.subs
    o = args.output

    for p in [v, a]:
        if not os.path.isfile(p):
            fail(f"Fichier manquant: {p}")

    if s:
        if not os.path.isfile(s):
            fail(f"Fichier sous-titres manquant: {s}")
        ext = pathlib.Path(s).suffix.lower()
        if ext not in (".srt", ".ass"):
            fail("Sous-titres: mettre un .srt ou .ass")

    # on cale la durée finale sur l'audio
    adur = ffprobe_duration(a)
    if adur <= 0:
        fail("Durée audio introuvable (ffprobe).")

    # filtre vidéo: scale/pad 1080x1920 + (optionnel) sous-titres
    vf_parts = [
        "scale=1080:1920:force_original_aspect_ratio=decrease",
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
        "setsar=1"
    ]
    if s:
        # ffmpeg accepte SRT/ASS directement via subtitles=
        # On quote le chemin pour éviter les soucis d'espaces/virgules
        vf_parts.append(f"subtitles={shlex.quote(os.path.abspath(s))}")

    vf = ",".join(vf_parts)

    cmd = [
        "ffmpeg","-nostdin","-y",
        "-i", v,
        "-i", a,
        "-vf", vf,
        "-map","0:v:0",
        "-map","1:a:0",
        "-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",
        "-c:a","aac","-b:a","192k",
        "-shortest",
        o
    ]

    # s’assurer que le dossier de sortie existe
    outdir = os.path.dirname(os.path.abspath(o)) or "."
    os.makedirs(outdir, exist_ok=True)

    print("CMD:", " ".join(shlex.quote(x) for x in cmd))
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        fail(f"ffmpeg a échoué (code {e.returncode})")

if __name__ == "__main__":
    main()
