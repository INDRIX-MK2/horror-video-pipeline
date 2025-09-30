#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, pathlib, subprocess, sys, shlex

# ---------------------------
#  Utils
# ---------------------------

def ffmpeg_silence(out_wav: pathlib.Path, dur: float) -> None:
    """Crée un silence PCM wav de durée dur (s)."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg","-nostdin","-y",
        "-f","lavfi","-i",f"anullsrc=r=44100:cl=mono",
        "-t",f"{dur:.3f}",
        "-c:a","pcm_s16le",
        str(out_wav)
    ]
    subprocess.run(cmd, check=True)

def write_concat_list(list_path: pathlib.Path, wavs: list[pathlib.Path]) -> None:
    """Écrit un fichier concat list avec chemins ABSOLUS et correctement quotés."""
    list_path.parent.mkdir(parents=True, exist_ok=True)
    with list_path.open("w", encoding="utf-8") as f:
        for w in wavs:
            # ffmpeg concat demuxer: format exact => file '/abs/path.wav'
            f.write(f"file {shlex.quote(str(w.resolve()))}\n")

def concat_wavs(list_path: pathlib.Path, out_path: pathlib.Path) -> None:
    """Concatène via demuxer concat."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg","-nostdin","-y",
        "-f","concat","-safe","0",
        "-i", str(list_path),
        "-c","copy",
        str(out_path)
    ]
    subprocess.run(cmd, check=True)

# ---------------------------
#  CLI
# ---------------------------

ap = argparse.ArgumentParser(description="Assemble la voix finale (titre + gap + histoire + gap + cta)")
ap.add_argument("--title-wav", default="audio/title.wav", help="WAV du titre (optionnel)")
ap.add_argument("--story-wav", default="audio/story.wav", help="WAV de l'histoire (requis)")
ap.add_argument("--cta-wav",   default="audio/cta.wav",   help="WAV du CTA (optionnel)")
ap.add_argument("--gap-title", type=float, default=1.0,   help="Silence (s) entre titre et histoire")
ap.add_argument("--gap-cta",   type=float, default=1.0,   help="Silence (s) entre histoire et CTA")
ap.add_argument("--out",       default="audio/voice.wav", help="WAV final concaténé")
ap.add_argument("--list-file", default="audio/voice.txt", help="Fichier liste pour concat (sera écrasé)")
args = ap.parse_args()

title_wav = pathlib.Path(args.title_wav)
story_wav = pathlib.Path(args.story_wav)
cta_wav   = pathlib.Path(args.cta_wav)
out_wav   = pathlib.Path(args.out)
list_file = pathlib.Path(args.list_file)

# ---------------------------
#  Validation & préparation
# ---------------------------

# On reconstruit la liste à chaque exécution
if list_file.exists():
    try: list_file.unlink()
    except: pass
list_file.parent.mkdir(parents=True, exist_ok=True)
out_wav.parent.mkdir(parents=True, exist_ok=True)

# Segments présents
segments: list[pathlib.Path] = []

# Titre (optionnel)
if title_wav.exists() and title_wav.stat().st_size > 0:
    segments.append(title_wav)

    # gap titre -> histoire
    if args.gap_title > 0:
        gap1 = pathlib.Path("audio/_gap_title_story.wav")
        ffmpeg_silence(gap1, args.gap_title)
        segments.append(gap1)

# Histoire (requis)
if not (story_wav.exists() and story_wav.stat().st_size > 0):
    print(f"[voice_elevenlabs] ERREUR: histoire manquante -> {story_wav}", file=sys.stderr)
    sys.exit(1)
segments.append(story_wav)

# gap histoire -> cta
if cta_wav.exists() and cta_wav.stat().st_size > 0 and args.gap_cta > 0:
    gap2 = pathlib.Path("audio/_gap_story_cta.wav")
    ffmpeg_silence(gap2, args.gap_cta)
    segments.append(gap2)

# CTA (optionnel)
if cta_wav.exists() and cta_wav.stat().st_size > 0:
    segments.append(cta_wav)

# Rien à concaténer ?
if not segments:
    print("[voice_elevenlabs] ERREUR: aucun segment audio trouvé (titre/histoire/cta).", file=sys.stderr)
    sys.exit(1)

# Écriture liste + concat
write_concat_list(list_file, segments)
try:
    concat_wavs(list_file, out_wav)
except subprocess.CalledProcessError as e:
    print(f"[voice_elevenlabs] ERREUR concat: {e}", file=sys.stderr)
    print(f"  Liste utilisée: {list_file}")
    if list_file.exists():
        print(list_file.read_text(encoding='utf-8'))
    sys.exit(1)

print(f"[voice_elevenlabs] OK -> {out_wav.resolve()}")
