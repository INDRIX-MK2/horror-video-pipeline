#!/usr/bin/env python3
import os, sys, json, pathlib, random, shutil, subprocess, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
AUDIO_DUR = ROOT / "audio" / "duration.json"
MANIFEST = ROOT / "manifests" / "horreur.txt"
BANK_DIR = ROOT / "bank_video" / "Horreur"
WORK = ROOT / "selected_media"
CACHE = WORK / "cache_sources"
LIST = WORK / "list.txt"
MERGED = WORK / "merged.mp4"

for d in [WORK, CACHE]:
    d.mkdir(parents=True, exist_ok=True)

if not AUDIO_DUR.exists():
    print("audio/duration.json manquant", file=sys.stderr)
    sys.exit(1)

voice_seconds = float(json.loads(AUDIO_DUR.read_text(encoding="utf-8")).get("seconds", 0.0))
if voice_seconds <= 0.1:
    print("Durée audio invalide", file=sys.stderr); sys.exit(1)

# Collecte des sources (URLs dans manifets/horreur.txt et/ou fichiers .mp4 locaux)
sources = []

def add_local_dir(p: pathlib.Path):
    if p.exists():
        for x in sorted(p.glob("*.mp4")):
            sources.append(x.resolve().as_posix())

def add_manifest(m: pathlib.Path):
    if not m.exists():
        return
    for line in m.read_text(encoding="utf-8").splitlines():
        ln = line.strip()
        if not ln or ln.startswith("#"):
            continue
        # si URL: on télécharge dans CACHE
        if ln.startswith("http://") or ln.startswith("https://"):
            try:
                url = ln
                # nom de fichier basé sur hash simple
                name = urllib.parse.quote_plus(url)
                dst = CACHE / (name + ".mp4")
                if not dst.exists() or dst.stat().st_size == 0:
                    with urllib.request.urlopen(url) as r, open(dst, "wb") as f:
                        shutil.copyfileobj(r, f)
                if dst.stat().st_size > 0:
                    sources.append(dst.resolve().as_posix())
            except Exception as e:
                print(f"Download raté: {ln} -> {e}", file=sys.stderr)
        else:
            p = (ROOT / ln).resolve()
            if p.exists() and p.suffix.lower()==".mp4":
                sources.append(p.as_posix())

add_manifest(MANIFEST)
add_local_dir(BANK_DIR)

if not sources:
    print("Aucune source vidéo trouvée (manifests/horreur.txt et/ou bank_video/Horreur).", file=sys.stderr)
    sys.exit(1)

random.shuffle(sources)

# On crée des segments successifs jusqu’à couvrir la durée de la voix (sans outro noir)
# Règle simple: segments de 6 à 8s, dernier segment ajusté à la durée restante.
remaining = voice_seconds
seg_index = 0
LIST.write_text("", encoding="utf-8")

def probe_duration(pth: str) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error","-show_entries","format=duration",
            "-of","default=nw=1:nk=1", pth
        ], text=True).strip()
        return float(out)
    except:
        return 0.0

src_cycle = 0
while remaining > 0.25:
    src = sources[src_cycle % len(sources)]
    src_cycle += 1
    seg_index += 1

    total = probe_duration(src)
    # cible par défaut
    target = 7.0
    if remaining < 7.0:
        target = remaining

    # si la source est plus courte, on prend ce qu'on peut (on coupera au besoin)
    seg_dur = min(target, max(2.0, total - 0.2) if total > 0 else target)

    # décalage aléatoire si possible
    start = 0.0
    if total > seg_dur + 0.5:
        import random
        start = random.uniform(0.0, total - seg_dur - 0.25)

    out = WORK / f"seg_{seg_index}.mp4"
    # Re-encode en 1080x1920 30fps, pad vertical, mute
    cmd = [
        "ffmpeg","-nostdin","-y",
        "-ss", f"{start:.3f}",
        "-t", f"{seg_dur:.3f}",
        "-i", src,
        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1",
        "-r","30","-c:v","libx264","-preset","veryfast","-crf","20",
        "-pix_fmt","yuv420p","-an", str(out)
    ]
    subprocess.run(cmd, check=True)

    # Écrit ABSOLU dans list.txt (imparable)
    LIST.open("a", encoding="utf-8").write(f"file '{out.resolve().as_posix()}'\n")
    remaining -= seg_dur

# Concat
subprocess.run([
    "ffmpeg","-nostdin","-y","-f","concat","-safe","0","-i",str(LIST),
    "-c","copy", str(MERGED)
], check=True)

print(f"Segments: {seg_index} -> {MERGED}")