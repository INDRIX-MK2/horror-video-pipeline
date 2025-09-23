# scripts/select_and_merge.py
import os, sys, time, json, shutil, pathlib, subprocess, urllib.request, urllib.error, random

ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST = pathlib.Path(os.environ.get("MANIFEST_FILE", "manifests/horreur.txt")).resolve()
VOICE_WAV = pathlib.Path(os.environ.get("VOICE_WAV", "audio/voice.wav")).resolve()
WORKDIR = ROOT / "selected_media"
DL_DIR = WORKDIR / "downloaded"
SEG_DIR = WORKDIR / "segments"
LIST_FILE = WORKDIR / "list.txt"
MERGED = WORKDIR / "merged.mp4"

# ---- util
def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kw)

def ffprobe_duration(p: pathlib.Path) -> float:
    try:
        out = run([
            "ffprobe","-v","error","-show_entries","format=duration",
            "-of","default=nokey=1:noprint_wrappers=1", str(p)
        ]).stdout.strip()
        return float(out) if out else 0.0
    except Exception:
        return 0.0

def ensure_dirs():
    WORKDIR.mkdir(parents=True, exist_ok=True)
    DL_DIR.mkdir(parents=True, exist_ok=True)
    SEG_DIR.mkdir(parents=True, exist_ok=True)
    # reset list.txt
    if LIST_FILE.exists(): LIST_FILE.unlink()

def read_manifest() -> list[str]:
    if not MANIFEST.exists():
        print(f"Manifest introuvable: {MANIFEST}", file=sys.stderr)
        sys.exit(1)
    lines = [l.strip() for l in MANIFEST.read_text(encoding="utf-8").splitlines()]
    urls = [l for l in lines if l and not l.startswith("#")]
    if not urls:
        print("Manifest vide.", file=sys.stderr); sys.exit(1)
    return urls

def download(url: str, dst: pathlib.Path) -> bool:
    try:
        # suit les redirections; timeout court; user-agent explicite
        req = urllib.request.Request(url, headers={"User-Agent":"curl/8"})
        with urllib.request.urlopen(req, timeout=60) as r, open(dst, "wb") as f:
            shutil.copyfileobj(r, f)
        return dst.stat().st_size > 0
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        print(f"[DL] Échec {url}: {e}", file=sys.stderr)
        return False

def reencode(src: pathlib.Path, out: pathlib.Path) -> bool:
    try:
        run([
            "ffmpeg","-nostdin","-y","-i",str(src),
            "-vf","scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1",
            "-r","30","-c:v","libx264","-crf","18","-pix_fmt","yuv420p","-an",
            str(out)
        ])
        return out.exists() and out.stat().st_size>0
    except subprocess.CalledProcessError as e:
        print(f"[ENC] Échec {src.name}: {e.stderr}", file=sys.stderr)
        return False

def abs_write_list(paths: list[pathlib.Path]):
    with open(LIST_FILE, "w", encoding="utf-8") as f:
        for p in paths:
            f.write(f"file '{p.as_posix()}'\n")

def concat_to_merged():
    run(["ffmpeg","-nostdin","-y","-f","concat","-safe","0","-i",str(LIST_FILE),"-c","copy",str(MERGED)])

# ---- main
def main():
    ensure_dirs()

    # durée réelle de la voix = cible
    if not VOICE_WAV.exists():
        print(f"Audio introuvable: {VOICE_WAV}", file=sys.stderr); sys.exit(1)
    target = ffprobe_duration(VOICE_WAV)
    if target <= 0:
        print("Durée audio invalide.", file=sys.stderr); sys.exit(1)
    print(f"[INFO] Durée voix cible: {target:.3f}s")

    urls = read_manifest()
    random.shuffle(urls)  # ordre aléatoire

    used_segments: list[pathlib.Path] = []
    total = 0.0
    idx = 0

    for i, url in enumerate(urls, start=1):
        # nom local déterministe
        ext = ".mp4"
        # déduire l'extension si visible
        for e in (".mp4",".mov",".mkv",".webm"):
            if e in url.lower():
                ext = e; break
        dl_path = DL_DIR / f"src_{i:03d}{ext}"
        ok = download(url, dl_path)
        if not ok:
            continue

        idx += 1
        seg_out = SEG_DIR / f"seg_{idx}.mp4"
        if not reencode(dl_path, seg_out):
            continue

        d = ffprobe_duration(seg_out)
        if d <= 0.1:
            continue

        used_segments.append(seg_out)
        total += d
        print(f"[ADD] {seg_out.name} (+{d:.2f}s) => cumul {total:.2f}s")

        if total >= target:
            break

    if not used_segments:
        print("Aucun segment utilisable.", file=sys.stderr); sys.exit(1)

    abs_write_list(used_segments)
    print(f"[INFO] list.txt écrit (absolu) avec {len(used_segments)} segments.")

    concat_to_merged()
    if not MERGED.exists() or MERGED.stat().st_size == 0:
        print("Concat échouée.", file=sys.stderr); sys.exit(1)

    print(f"[OK] merged => {MERGED} (≈ {ffprobe_duration(MERGED):.2f}s)")

if __name__ == "__main__":
    main()