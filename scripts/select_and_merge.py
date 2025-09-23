#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess
from pathlib import Path

# ---------- Config ----------
OUT_DIR = Path("selected_media")              # dépôt des segments + merge
MANIFEST = OUT_DIR / "manifest.txt"           # liste des sources (une par ligne)
MERGED = OUT_DIR / "merged.mp4"               # sortie concat finale
SEG_PATTERN = "seg_{:03d}.mp4"                # segments nommés seg_001.mp4, ...
LIST_FILE = OUT_DIR / "list.txt"              # liste ffconcat
# Réglages ffmpeg segment
SCALE_VF = (
    "scale=1080:1920:force_original_aspect_ratio=decrease,"
    "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1"
)
FPS = "30"
CRF = "18"
PIX_FMT = "yuv420p"
VCODEC = "libx264"
PRESET = "medium"  # équilibré


def which(cmd: str) -> str:
    p = shutil.which(cmd)
    if not p:
        print(f"Erreur: commande introuvable: {cmd}", file=sys.stderr)
        sys.exit(127)
    return p


def read_manifest(manifest: Path) -> list[Path]:
    if not manifest.exists():
        print(f"Erreur: manifest introuvable: {manifest}", file=sys.stderr)
        sys.exit(1)
    items: list[Path] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = Path(line)
        if not p.exists():
            print(f"Attention: source absente, ignorée: {line}", file=sys.stderr)
            continue
        # On n'accepte que des fichiers
        if not p.is_file():
            print(f"Attention: pas un fichier, ignoré: {line}", file=sys.stderr)
            continue
        items.append(p)
    if not items:
        print("Erreur: aucune source exploitable dans le manifest.", file=sys.stderr)
        sys.exit(1)
    return items


def run_ffmpeg_segment(src: Path, dst: Path) -> None:
    # Ré-encode en 1080x1920/30fps pour concat propre
    cmd = [
        "ffmpeg", "-nostdin", "-y",
        "-i", str(src),
        "-vf", SCALE_VF,
        "-r", FPS,
        "-c:v", VCODEC,
        "-preset", PRESET,
        "-crf", CRF,
        "-pix_fmt", PIX_FMT,
        "-an",
        str(dst),
    ]
    subprocess.run(cmd, check=True)


def ffconcat_quote_abspath(p: Path) -> str:
    """
    Retourne une ligne 'file '...'' pour le concat demuxer avec chemin ABSOLU.
    On échappe les apostrophes en fermant/rouvrant la quote : foo'bar -> 'foo'\''bar'
    (méthode universelle)
    """
    s = p.resolve().as_posix().replace("'", r"'\''")
    return f"file '{s}'"


def concat_segments(list_file: Path, out_file: Path) -> None:
    # -safe 0 requis pour chemins absolus
    cmd = [
        "ffmpeg", "-nostdin", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        str(out_file),
    ]
    subprocess.run(cmd, check=True)


def main() -> None:
    which("ffmpeg")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Nettoyage
    if LIST_FILE.exists():
        LIST_FILE.unlink()
    if MERGED.exists():
        MERGED.unlink()
    for old in OUT_DIR.glob("seg_*.mp4"):
        try:
            old.unlink()
        except Exception:
            pass

    sources = read_manifest(MANIFEST)

    # Segmentation
    seg_paths: list[Path] = []
    for i, src in enumerate(sources, start=1):
        seg = OUT_DIR / SEG_PATTERN.format(i)
        print(f"[{i}/{len(sources)}] Encodage segment: {src} -> {seg}")
        run_ffmpeg_segment(src, seg)
        seg_paths.append(seg)

    if not seg_paths:
        print("Erreur: aucun segment généré.", file=sys.stderr)
        sys.exit(1)

    # Ecriture list.txt avec CHEMINS ABSOLUS
    with LIST_FILE.open("w", encoding="utf-8") as f:
        for seg in seg_paths:
            f.write(ffconcat_quote_abspath(seg) + "\n")

    # Concat
    print(f"Concaténation de {len(seg_paths)} segments -> {MERGED}")
    concat_segments(LIST_FILE, MERGED)

    # Vérification finale
    if not MERGED.exists() or MERGED.stat().st_size == 0:
        print("Erreur: échec concat (fichier final manquant ou vide).", file=sys.stderr)
        sys.exit(1)

    print("OK: merged =", MERGED.resolve().as_posix())


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"Erreur FFmpeg (code {e.returncode}) sur: {' '.join(e.cmd)}", file=sys.stderr)
        sys.exit(e.returncode)
    except Exception as e:
        print(f"Erreur: {e}", file=sys.stderr)
        sys.exit(1)