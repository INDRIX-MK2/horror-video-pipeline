#!/usr/bin/env python3
import os, sys, pathlib, urllib.request, random, subprocess, shlex, tempfile

AUDIO = pathlib.Path("audio/voice.mp3")
if not AUDIO.exists():
    print("Audio introuvable: audio/voice.mp3", file=sys.stderr)
    sys.exit(1)

def ffprobe_duration(p: pathlib.Path) -> float:
    cmd = ["ffprobe","-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",str(p)]
    out = subprocess.check_output(cmd).decode("utf-8").strip()
    return float(out)

voice_dur = ffprobe_duration(AUDIO)

MANIFEST_URL = os.environ.get("MANIFEST_URL","").strip()
theme_dir = pathlib.Path("bank_video/Horreur")
dl_dir = pathlib.Path("bank_video/_cache")
dl_dir.mkdir(parents=True, exist_ok=True)

def download_all(urls):
    out = []
    for i,u in enumerate(urls,1):
        try:
            name = f"clip_{i:03d}.mp4"
            dest = dl_dir/name
            if not dest.exists():
                urllib.request.urlretrieve(u, dest.as_posix())
            out.append(dest)
        except Exception as e:
            print(f"Skip {u}: {e}", file=sys.stderr)
    return out

sources = []
if MANIFEST_URL:
    try:
        with urllib.request.urlopen(MANIFEST_URL, timeout=60) as resp:
            body = resp.read().decode("utf-8")
            urls = [l.strip() for l in body.splitlines() if l.strip()]
            sources = download_all(urls)
    except Exception as e:
        print(f"MANIFEST_URL échec: {e}", file=sys.stderr)

if not sources:
    theme_dir.mkdir(parents=True, exist_ok=True)
    sources = sorted(theme_dir.glob("*.mp4"))

if not sources:
    print("Aucun clip source trouvé.", file=sys.stderr)
    sys.exit(1)

random.shuffle(sources)

sel_dir = pathlib.Path("selected_media")
sel_dir.mkdir(parents=True, exist_ok=True)
list_file = sel_dir/"list.txt"
if list_file.exists():
    list_file.unlink()

# Sélection jusqu'à couvrir la durée de la voix
acc = 0.0
index = 0
segments = []
for src in sources:
    index += 1
    out = sel_dir/f"seg_{index}.mp4"
    # Re-encode + pillarbox
    cmd = [
        "ffmpeg","-nostdin","-y","-i",str(src),
        "-vf","scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1",
        "-r","30","-c:v","libx264","-crf","18","-pix_fmt","yuv420p","-an",str(out)
    ]
    subprocess.run(cmd, check=True)
    # Durée segment
    seg_dur = ffprobe_duration(out)
    acc += seg_dur
    segments.append(out)
    with list_file.open("a", encoding="utf-8") as f:
        f.write(f"file '{out.as_posix()}'\n")
    if acc >= voice_dur + 0.25:
        break

if not segments:
    print("Aucun segment retenu", file=sys.stderr)
    sys.exit(1)

# Concat
merged = sel_dir/"merged.mp4"
subprocess.run(["ffmpeg","-nostdin","-y","-f","concat","-safe","0","-i",str(list_file),"-c","copy",str(merged)], check=True)
print(f"OK: {merged}")