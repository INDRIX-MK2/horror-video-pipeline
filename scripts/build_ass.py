#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, pathlib, subprocess, sys, re, math

ap = argparse.ArgumentParser(description="Génère un .ass centré (titre + histoire + cta)")
ap.add_argument("--transcript", required=True, help="Texte principal (histoire)")
ap.add_argument("--audio", required=True, help="Audio narratif total (voice.wav)")
ap.add_argument("--out", default="subs/captions.ass")

# Style par défaut (centré, jaune)
ap.add_argument("--font", default="Arial")
ap.add_argument("--size", type=int, default=80)
ap.add_argument("--colour", default="&H00FFFF00")          # jaune vif
ap.add_argument("--outline-colour", default="&H96000000")  # halo sombre
ap.add_argument("--back-colour", default="&H32000000")     # ombre arrière
ap.add_argument("--outline", type=float, default=3.0)
ap.add_argument("--shadow", type=float, default=2.0)
ap.add_argument("--align", type=int, default=5)            # 5 = centre
ap.add_argument("--marginv", type=int, default=300)        # distance du bas/centre

# Mise en forme du texte
ap.add_argument("--max-words", type=int, default=4)        # 4 mots / ligne
ap.add_argument("--max-lines", type=int, default=4)        # 4 lignes max par bloc
ap.add_argument("--lead", type=float, default=0.0)         # avance/retard global (s)
ap.add_argument("--speed", type=float, default=1.0)        # facteur vitesse 1.0 = normal

# Fichiers optionnels pour Titre / CTA
ap.add_argument("--title-file", default="story/title.txt")
ap.add_argument("--cta-file",   default="story/cta.txt")
ap.add_argument("--title-dur", type=float, default=2.0)    # durée d’affichage du titre
ap.add_argument("--title-gap", type=float, default=1.0)    # gap après le titre
ap.add_argument("--cta-dur",   type=float, default=2.5)    # durée d’affichage du CTA
ap.add_argument("--gap-before-cta", type=float, default=1.0)

args = ap.parse_args()

tpath = pathlib.Path(args.transcript)
apath = pathlib.Path(args.audio)
opath = pathlib.Path(args.out)
opath.parent.mkdir(parents=True, exist_ok=True)

if not tpath.exists() or not tpath.stat().st_size:
    print("Transcript introuvable/vide", file=sys.stderr); sys.exit(1)
if not apath.exists() or not apath.stat().st_size:
    print("Audio introuvable/vide", file=sys.stderr); sys.exit(1)

def ffprobe_duration(p: pathlib.Path) -> float:
    try:
        out = subprocess.check_output(
            ["ffprobe","-v","error","-show_entries","format=duration","-of","default=nk=1:nw=1", str(p)],
            stderr=subprocess.DEVNULL
        ).decode("utf-8","ignore").strip()
        return max(0.0, float(out))
    except Exception:
        return 0.0

def to_ass_ts(sec: float) -> str:
    if sec < 0: sec = 0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

def clean_text(s: str) -> str:
    s = s.replace("\r", "")
    # supprime didascalies
    s = re.sub(r"\[[^\]]*\]", "", s)
    s = re.sub(r"\([^)]*\)", "", s)
    # normalise espaces
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def split_sentences(txt: str):
    # coupe sur . ! ? tout en conservant la ponctuation
    parts = re.split(r"([\.!?…])", txt)
    buf, sentences = "", []
    for i in range(0, len(parts), 2):
        seg = parts[i].strip()
        end = parts[i+1] if i+1 < len(parts) else ""
        if not seg: continue
        sentences.append((seg + end).strip())
    if not sentences and txt:
        sentences = [txt.strip()]
    return sentences

def wrap_words(sentence: str, max_words: int, max_lines: int):
    ws = sentence.split()
    lines, cur = [], []
    for w in ws:
        cur.append(w)
        if len(cur) >= max_words:
            lines.append(" ".join(cur)); cur=[]
            if len(lines) >= max_lines:  # on arrête si dépasse
                cur = []
                break
    if cur:
        lines.append(" ".join(cur))
    return lines

audio_dur = ffprobe_duration(apath)

# ----- charge textes -----
story_raw = clean_text(tpath.read_text(encoding="utf-8"))
title_txt = ""
cta_txt   = ""

tfile = pathlib.Path(args.title_file)
if tfile.exists() and tfile.stat().st_size:
    title_txt = clean_text(tfile.read_text(encoding="utf-8"))

cfile = pathlib.Path(args.cta_file)
if cfile.exists() and cfile.stat().st_size:
    cta_txt = clean_text(cfile.read_text(encoding="utf-8"))

# ----- Segmentation du texte principal -----
sentences = split_sentences(story_raw)

# Chaque phrase -> lignes (4 mots max par défaut)
blocks = []  # liste de blocs, chaque bloc = ["ligne1","ligne2",...]
for s in sentences:
    lines = wrap_words(s, args.max_words, args.max_lines)
    if not lines:
        continue
    blocks.append(lines)

if not blocks:
    print("[build_ass] Aucun contenu détecté dans l'histoire.", file=sys.stderr)
    sys.exit(1)

# ======= Calcul du minutage =======
# Répartitions :
#   [Titre] (facultatif) durée = title_dur
#   + title_gap
#   [Story] durée = reste
#   + gap_before_cta
#   [CTA] (facultatif) durée = cta_dur
#
# On borne tout à la durée audio et on applique lead/speed sans dérive cumulative.

t = 0.0
events = []

def add_event(start: float, end: float, txt: str):
    start = max(0.0, start + args.lead)
    end   = max(start, end + args.lead)
    start /= max(1e-6, args.speed)
    end   /= max(1e-6, args.speed)
    # clamp à la durée audio
    start = min(start, audio_dur)
    end   = min(end, audio_dur)
    if end - start <= 0.01:
        return
    # éviter les backslashes parasites
    safe = txt.replace("\\", "").strip()
    events.append((start, end, safe))

# Titre
if title_txt:
    add_event(0.0, min(args.title_dur, audio_dur), title_txt)
    t = args.title_dur + args.title_gap
else:
    t = 0.0

# Si CTA prévu, réserver sa place à la fin
cta_slot = args.cta_dur if cta_txt else 0.0
gap_before_cta = args.gap_before_cta if cta_txt else 0.0

story_space = max(0.0, audio_dur - t - gap_before_cta - cta_slot)
if story_space <= 0.0:
    story_space = 0.0

# Durée par bloc = partage égal
nb = len(blocks)
per = story_space / nb if nb > 0 else 0.0

cur = t
for lines in blocks:
    s = cur
    e = min(audio_dur, s + per)
    # Texte multi-lignes (2–4 lignes)
    txt = "\n".join(lines)
    add_event(s, e, txt)
    cur = e

# Gap + CTA
if cta_txt:
    cur = min(audio_dur, cur + gap_before_cta)
    add_event(cur, min(audio_dur, cur + args.cta_dur), cta_txt)

if not events:
    print("[build_ass] Aucun événement à écrire (vérifie la durée audio).", file=sys.stderr)
    sys.exit(1)

# ======= Écriture ASS =======
hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTok,{args.font},{args.size},{args.colour},&H00000000,{args.outline-colour},{args.back-colour},0,0,0,0,100,100,0,0,1,{args.outline},{args.shadow},{args.align},40,40,{args.marginv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".replace("\r\n","\n")

with opath.open("w", encoding="utf-8") as f:
    f.write(hdr)
    for s,e,txt in events:
        f.write(f"Dialogue: 0,{to_ass_ts(s)},{to_ass_ts(e)},TikTok,,0,0,0,,{txt}\n")

print(f"[build_ass] écrit: {opath} (durée audio: {audio_dur:.2f}s, events: {len(events)})")
