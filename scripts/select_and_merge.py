#!/usr/bin/env python3
import argparse, pathlib, sys, os, urllib.request, tempfile, subprocess, shlex, random

ap = argparse.ArgumentParser()
ap.add_argument("--manifest", required=True, help="Fichier texte : 1 URL .mp4 par ligne (Dropbox ?dl=1)")
ap.add_argument("--audio", required=True, help="audio/voice.wav pour calculer la durée cible")
ap.add_argument("--out", required=True, help="selected_media/merged.mp4")
args = ap.parse_args()

manifest = pathlib.Path(args.manifest)
audio = pathlib.Path(args.audio)
out = pathlib.Path(args.out)

out.parent.mkdir(parents=True, exist_ok=True)
work = out.parent  # selected_media
raw_dir = work / "raw"
enc_dir = work / "enc"
raw_dir.mkdir(exist_ok=True)
enc_dir.mkdir(exist_ok=True)

if not manifest.exists() or not manifest.stat().st_size:
    print(f"Manifest introuvable/vide: {manifest}", file=sys.stderr); sys.exit(1)
if not audio.exists() or not audio.stat().st_size:
    print(f"Audio introuvable/vide: {audio}", file=sys.stderr); sys.exit(1)

def ff_ok():
    try: subprocess.run(["ffmpeg","-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); return True
    except: return False
def fp_ok():
    try: subprocess.run(["ffprobe","-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); return True
    except: return False
if not (ff_ok() and fp_ok()):
    print("ffmpeg/ffprobe manquants", file=sys.stderr); sys.exit(1)

def dur_media(p):
    outp = subprocess.check_output([
        "ffprobe","-v","error","-select_streams","v:0","-show_entries","stream=duration",
        "-of","default=nk=1:nw=1", str(p)
    ]).decode("utf-8","ignore").strip()
    try: return float(outp)
    except: return 0.0

def dur_audio(p):
    outp = subprocess.check_output([
        "ffprobe","-v","error","-show_entries","format=duration",
        "-of","default=nk=1:nw=1", str(p)
    ]).decode("utf-8","ignore").strip()
    try: return float(outp)
    except: return 0.0

target = max(0.01, dur_audio(audio))

# 1) Lire URLs
urls = [ln.strip() for ln in manifest.read_text(encoding="utf-8").splitlines() if ln.strip()]
if not urls:
    print("Aucune URL dans le manifest", file=sys.stderr); sys.exit(1)

# 2) Télécharger → raw/clip_N.mp4
dl_paths = []
for i,u in enumerate(urls, start=1):
    try:
        fn = raw_dir / f"clip_{i:03d}.mp4"
        # urllib récupère tout en mémoire si file://, sinon HTTP
        with urllib.request.urlopen(u, timeout=120) as resp, open(fn, "wb") as f:
            f.write(resp.read())
        dl_paths.append(fn)
    except Exception as e:
        print(f"Skip URL {u}: {e}", file=sys.stderr)

if not dl_paths:
    print("Aucun clip téléchargé", file=sys.stderr); sys.exit(1)

# 3) Ré-encoder chaque clip en 1080x1920/30fps, h264 yuv420p sans audio
enc_paths = []
for i,src in enumerate(dl_paths, start=1):
    outp = enc_dir / f"seg_{i:03d}.mp4"
    cmd = [
        "ffmpeg","-nostdin","-y","-i",str(src),
        "-vf","scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1",
        "-r","30","-c:v","libx264","-crf","18","-pix_fmt","yuv420p",
        "-an", str(outp)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    enc_paths.append(outp)

# 4) Sélectionner assez de segments pour couvrir la durée audio
sel = []
total = 0.0
i = 0
while total < target + 0.3:  # petite marge
    p = enc_paths[i % len(enc_paths)]
    d = dur_media(p)
    sel.append((p, d))
    total += d
    i += 1

# 5) Concat via concat demuxer avec CHEMINS ABSOLUS (imparable)
list_file = work / "list.txt"
with list_file.open("w", encoding="utf-8") as f:
    for p,_ in sel:
        f.write(f"file '{p.resolve().as_posix()}'\n")

subprocess.run([
    "ffmpeg","-nostdin","-y","-f","concat","-safe","0","-i",str(list_file),
    "-c","copy", str(out)
], check=True)

print(f"[select_and_merge] écrit: {out} (couverture ~{total:.2f}s pour audio {target:.2f}s)")