#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, argparse, pathlib, subprocess, re, math

# -----------------------
#    Arguments CLI
# -----------------------
ap = argparse.ArgumentParser(
    description="Build ASS subtitles (phrase par phrase) anti-dérive, avec wrap en N lignes."
)
ap.add_argument("--transcript", required=True, help="Texte de l'histoire (UTF-8).")
ap.add_argument("--audio", required=True, help="Fichier audio (voice.wav) pour caler la durée.")
ap.add_argument("--out", default="subs/captions.ass", help="Sortie ASS (par défaut subs/captions.ass).")

# Style principal (modifiable à la volée)
ap.add_argument("--font", default="Arial", help="Police (ASS).")
ap.add_argument("--size", type=int, default=80, help="Taille de police (défaut 80).")
ap.add_argument("--colour", default="&H00FFFF00", help="PrimaryColour ASS (ex: &H00FFFF00 = jaune).")
ap.add_argument("--outline-colour", default="&H00000000", help="OutlineColour ASS (défaut noir).")
ap.add_argument("--back-colour", default="&H64000000", help="BackColour ASS (défaut semi-noir).")
ap.add_argument("--outline", type=float, default=3.0, help="Épaisseur contour (défaut 3).")
ap.add_argument("--shadow", type=float, default=2.0, help="Ombre (défaut 2).")
ap.add_argument("--align", type=int, default=5, help="Alignment ASS (5=center milieu).")
ap.add_argument("--marginv", type=int, default=200, help="MarginV (défaut 200).")

# Découpage
ap.add_argument("--max-words", type=int, default=4, help="Mots max par ligne (défaut 4).")
ap.add_argument("--max-lines", type=int, default=4, help="Lignes max par évènement (défaut 4).")

# Ajustements timing globaux
ap.add_argument("--lead", type=float, default=0.0, help="Décalage global (s) des sous-titres.")
ap.add_argument("--speed", type=float, default=1.0, help="Facteur global vitesses des sous-titres.")

args = ap.parse_args()

tpath = pathlib.Path(args.transcript)
apath = pathlib.Path(args.audio)
opath = pathlib.Path(args.out)
opath.parent.mkdir(parents=True, exist_ok=True)

if not tpath.exists() or not tpath.stat().st_size:
    print("[build_ass] Transcript introuvable/vide:", tpath, file=sys.stderr); sys.exit(1)
if not apath.exists() or not apath.stat().st_size:
    print("[build_ass] Audio introuvable/vide:", apath, file=sys.stderr); sys.exit(1)

# -----------------------
#   Utilitaires
# -----------------------
def ffprobe_duration(p: pathlib.Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error","-show_entries","format=duration",
            "-of","default=nk=1:nw=1", str(p)
        ]).decode("utf-8","ignore").strip()
        return float(out)
    except Exception:
        return 0.0

def to_ass_ts(sec: float) -> str:
    if sec < 0: sec = 0.0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

def clean_text(s: str) -> str:
    # Retire didascalies et labels de locuteur (Voix 1:, Narrateur:, etc.)
    s = re.sub(r"\[[^\]]*\]", " ", s)
    s = re.sub(r"\([^)]+\)", " ", s)
    s = re.sub(r"^(?:voix|narrateur|speaker)\s*\d*\s*:\s*", "", s, flags=re.IGNORECASE|re.MULTILINE)
    # Retire balises ASS {…}
    s = re.sub(r"\{[^}]*\}", " ", s)
    # Normalise espaces
    s = re.sub(r"\s+", " ", s).strip()
    return s

def split_sentences(s: str):
    # Split "phrase par phrase" en gardant la ponctuation
    # On découpe sur . ! ? ; : (et équivalents) en conservant le séparateur
    parts = re.split(r"([\.!\?;:…])", s)
    out = []
    buf = ""
    for i in range(0, len(parts), 2):
        seg = parts[i].strip()
        punct = parts[i+1] if i+1 < len(parts) else ""
        if not seg:
            continue
        sent = (seg + punct).strip()
        if sent:
            out.append(sent)
    return out

def wrap_words(text: str, max_words: int) -> list[str]:
    # Renvoie des lignes de <= max_words mots (pas de "\" parasite)
    ws = text.split()
    lines = []
    for i in range(0, len(ws), max_words):
        lines.append(" ".join(ws[i:i+max_words]))
    return lines

# -----------------------
#   Lecture & préparation
# -----------------------
audio_dur = max(0.01, ffprobe_duration(apath))
raw = tpath.read_text(encoding="utf-8", errors="ignore")
raw = clean_text(raw)

# Sentences -> Lines (wrap) -> Blocks (jusqu'à max_lines)
sentences = split_sentences(raw)

line_list = []  # toutes les lignes (chaque entrée = une ligne de <= max_words)
for sent in sentences:
    line_list.extend(wrap_words(sent, args.max_words))

if not line_list:
    print("[build_ass] Aucune ligne après découpage.", file=sys.stderr)
    sys.exit(1)

# Groupe par blocs de max_lines (chaque bloc = 1 évènement ASS)
blocks = []
for i in range(0, len(line_list), args.max_lines):
    bloc_lines = line_list[i:i+args.max_lines]
    blocks.append(bloc_lines)

# -----------------------
#   Timing anti-dérive
# -----------------------
# durée par mot globale = audio_dur / total_mots
total_words = sum(len(" ".join(bl).split()) for bl in blocks)
if total_words == 0:
    print("[build_ass] Aucun mot détecté.", file=sys.stderr)
    sys.exit(1)

sec_per_word = audio_dur / total_words

events = []
t = 0.0
for bl in blocks:
    text = r"\N".join(bl)  # \N = saut de ligne ASS; pas de "\" final
    n_w = max(1, len(" ".join(bl).split()))
    dur = n_w * sec_per_word
    s = t
    e = s + dur
    events.append((s, e, text))
    t = e

# Ajustements globaux (lead/speed) sans ré-accumuler d'arrondis
def adj(x: float) -> float:
    return max(0.0, args.lead + (x * args.speed))

events = [(adj(s), adj(e), txt) for (s, e, txt) in events]
events = [(s, min(e, audio_dur), txt) for (s, e, txt) in events]

# -----------------------
#     En-tête ASS
# -----------------------
hdr = (
    "[Script Info]\n"
    "ScriptType: v4.00+\n"
    "PlayResX: 1080\n"
    "PlayResY: 1920\n"
    "WrapStyle: 2\n"
    "ScaledBorderAndShadow: yes\n"
    "YCbCr Matrix: TV.709\n"
    "\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
    "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
    "Alignment, MarginL, MarginR, MarginV, Encoding\n"
    f"Style: TikTok,{args.font},{args.size},{args.colour},&H00000000,{args.outline_colour},{args.back_colour},"
    f"0,0,0,0,100,100,0,0,1,{args.outline},{args.shadow},{args.align},40,40,{args.marginv},1\n"
    "\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
)

# -----------------------
#     Écriture ASS
# -----------------------
with opath.open("w", encoding="utf-8") as f:
    f.write(hdr)
    for s, e, txt in events:
        # Nettoyage minimal pour éviter d'injecter des tags ASS involontaires
        safe = re.sub(r"\{[^}]*\}", "", txt)
        f.write(f"Dialogue: 0,{to_ass_ts(s)},{to_ass_ts(e)},TikTok,,0,0,0,,{safe}\n")

print(f"[build_ass] écrit: {opath} (durée audio détectée: {audio_dur:.2f}s, "
      f"évènements: {len(events)}, mots: {total_words}, sec/mot: {sec_per_word:.3f})")