#!/usr/bin/env python3
import argparse, pathlib, sys, subprocess, shlex, json, re, os, tempfile
from urllib.parse import urlparse
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent

def ffprobe_duration(p: pathlib.Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error",
            "-show_entries","format=duration",
            "-of","default=nk=1:nw=1",
            str(p)
        ]).decode("utf-8","ignore").strip()
        return float(out)
    except Exception:
        return 0.0

def is_url(s: str) -> bool:
    try:
        u = urlparse(s.strip())
        return u.scheme in ("http","https")
    except Exception:
        return False

def safe_lines(txt: str):
    for ln in txt.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        yield ln

def download(url: str, out: pathlib.Path):
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(out, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024*256):
                if chunk:
                    f.write(chunk)

def build_faded_clip(src: pathlib.Path, dst: pathlib.Path, keep_dur: float, fade_d: float):
    """Recadre 1080x1920 @30fps + fade in/out noir puis encode H.264.
       keep_dur: durée désirée de ce segment (en s) après tronquage.
       fade_d: durée du fade in et du fade out (s), ajustée si segment court.
    """
    if keep_dur <= 0.05:
        raise ValueError("keep_dur trop court")

    # Ajuste fade si segment trop court
    fin = min(fade_d, max(0.05, keep_dur * 0.25))
    fout = min(fade_d, max(0.05, keep_dur * 0.25))
    st_out = max(0.0, keep_dur - fout)

    vf = (
        "scale=1200:2133:force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        f"fade=t=in:st=0:d={fin:.3f},"
        f"fade=t=out:st={st_out:.3f}:d={fout:.3f}"
    )
    cmd = [
        "ffmpeg","-nostdin","-y",
        "-i", str(src),
        "-t", f"{keep_dur:.3f}",
        "-an",
        "-vf", vf,
        "-r","30",
        "-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",
        str(dst)
    ]
    subprocess.run(cmd, check=True)

def main():
    ap = argparse.ArgumentParser(description="Select clips to match audio length, add fade-to-black between clips, and merge.")
    ap.add_argument("--manifest", required=True, help="Fichier manifeste (chemins locaux ou URLs, 1 par ligne)")
    ap.add_argument("--audio",    required=True, help="Audio narratif (voice.wav)")
    ap.add_argument("--out",      required=True, help="Vidéo fusionnée de sortie (e.g., selected_media/merged.mp4)")
    ap.add_argument("--fade",     type=float, default=0.30, help="Durée fade in/out par segment (s)")
    ap.add_argument("--min-keep", type=float, default=1.00, help="Durée minimale utile d’un segment (s)")
    args = ap.parse_args()

    mpath = (ROOT / args.manifest).resolve() if not os.path.isabs(args.manifest) else pathlib.Path(args.manifest).resolve()
    apath = (ROOT / args.audio).resolve()    if not os.path.isabs(args.audio)    else pathlib.Path(args.audio).resolve()
    outp  = (ROOT / args.out).resolve()      if not os.path.isabs(args.out)      else pathlib.Path(args.out).resolve()

    smdir = (ROOT / "selected_media").resolve()
    smdir.mkdir(parents=True, exist_ok=True)
    outp.parent.mkdir(parents=True, exist_ok=True)

    if not mpath.exists() or mpath.stat().st_size == 0:
        print(f"[select_and_merge] Manifeste introuvable/vide: {mpath}", file=sys.stderr); sys.exit(1)
    if not apath.exists() or apath.stat().st_size == 0:
        print(f"[select_and_merge] Audio introuvable/vide: {apath}", file=sys.stderr); sys.exit(1)

    # Durée cible = durée audio
    audio_dur = ffprobe_duration(apath)
    if audio_dur <= 0.1:
        print("[select_and_merge] Durée audio invalide.", file=sys.stderr); sys.exit(1)

    # Récupère les sources (locales ou URLs)
    sources = list(safe_lines(mpath.read_text(encoding="utf-8")))
    if not sources:
        print("[select_and_merge] Aucune entrée valide dans le manifeste.", file=sys.stderr); sys.exit(1)

    # Prépare des chemins locaux pour chaque entrée
    local_entries = []
    for idx, src in enumerate(sources, start=1):
        if is_url(src):
            dst = smdir / f"src_{idx:02d}.mp4"
            if not dst.exists() or dst.stat().st_size == 0:
                try:
                    download(src, dst)
                except Exception as e:
                    print(f"[select_and_merge] Téléchargement échoué ({src}): {e}", file=sys.stderr)
                    continue
            local_entries.append(dst)
        else:
            p = (ROOT / src).resolve() if not os.path.isabs(src) else pathlib.Path(src).resolve()
            if p.exists() and p.stat().st_size > 0:
                local_entries.append(p)

    if not local_entries:
        print("[select_and_merge] Aucun média local exploitable.", file=sys.stderr); sys.exit(1)

    # Choisit et transforme les segments jusqu'à couvrir audio_dur
    keep_paths = []
    elapsed = 0.0
    seg_idx = 0

    for p in local_entries:
        src_d = ffprobe_duration(p)
        if src_d < args.min_keep:
            continue
        remain = audio_dur - elapsed
        if remain <= 0.05:
            break
        use_d = min(src_d, remain)
        if use_d < args.min_keep:
            # si dernier petit reste, on l’étire un chouïa plutôt que le zapper
            if remain >= 0.5:
                continue
            use_d = max(0.5, remain)

        seg_idx += 1
        out_seg = smdir / f"seg_{seg_idx:02d}_fx.mp4"
        try:
            build_faded_clip(p, out_seg, keep_dur=use_d, fade_d=args.fade)
        except Exception as e:
            print(f"[select_and_merge] Échec build fade pour {p}: {e}", file=sys.stderr)
            seg_idx -= 1
            continue

        keep_paths.append(out_seg.resolve())
        elapsed += use_d

        if elapsed >= audio_dur - 0.05:
            break

    if not keep_paths:
        print("[select_and_merge] Aucun segment retenu.", file=sys.stderr); sys.exit(1)

    # Écrit un list.txt avec chemins ABSOLUS (imparable)
    list_file = smdir / "list.txt"
    with list_file.open("w", encoding="utf-8") as f:
        for kp in keep_paths:
            f.write(f"file '{kp.as_posix()}'\n")

    # Concat demuxer (streams homogènes), remux direct
    cmd = [
        "ffmpeg","-nostdin","-y",
        "-f","concat","-safe","0",
        "-i", str(list_file),
        "-c","copy",
        str(outp)
    ]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        # Si remux échoue (paramètres divergents), on réencode une dernière fois proprement
        print("[select_and_merge] Remux copy a échoué, réencodage global…", file=sys.stderr)
        cmd2 = [
            "ffmpeg","-nostdin","-y",
            "-f","concat","-safe","0","-i", str(list_file),
            "-r","30",
            "-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",
            str(outp)
        ]
        subprocess.run(cmd2, check=True)

    print(f"[select_and_merge] OK -> {outp}")

if __name__ == "__main__":
    main()