#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, argparse, pathlib, subprocess, re

# -----------------------------
# CLI
# -----------------------------
ap = argparse.ArgumentParser(description="Génère un .ass centré, phrase par phrase, avec wrap multi-lignes.")
ap.add_argument("--transcript", required=True, help="Fichier texte de la narration (histoire).")
ap.add_argument("--audio",      required=True, help="Fichier audio (wav/mp3) pour caler la durée totale.")
ap.add_argument("--out",        default="subs/captions.ass", help="Chemin de sortie .ass")

# Style ASS (modifiables à la volée)
ap.add_argument("--font",   default="Arial")
ap.add_argument("--size",   type=int, default=60)
ap.add_argument("--colour", default="&H00FFFF00")  # Jaune par défaut (AABBGGRR)
ap.add_argument("--outline-colour", dest="outline_colour", default="&H00000000")
ap.add_argument("--back-colour",    dest="back_colour",    default="&H64000000")
ap.add_argument("--outline", type=int, default=3)
ap.add_argument("--shadow",  type=int, default=2)
ap.add_argument("--align",   type=int, default=5)  # 5 = centre milieu (TikTok)
ap.add_argument("--marginv", type=int, default=200)

# Contrôle du rendu des lignes
ap.add_argument("--max-words", type=int, default=4, help="Mots max par ligne.")
ap.add_argument("--max-lines", type=int, default=3, help="Lignes max par phrase.")

# Anti-dérive simple
ap.add_argument("--lead",  type=float, default=0.0, help="Décalage initial (s).")
ap.add_argument("--speed", type=float, default=1.0, help="Vitesse (>1 accélère, <1 ralentit).")

args = ap.parse_args()

tpath = pathlib.Path(args.transcript)
apath = pathlib.Path(args.audio)
opath = pathlib.Path(args.out)
opath.parent.mkdir(parents=True, exist_ok=True)

if not tpath.exists() or not tpath.stat().st_size:
    print("Transcript introuvable/vide", file=sys.stderr); sys.exit(1)
if not apath.exists() or not apath.stat().st_size:
    print("Audio introuvable/vide", file=sys.stderr); sys.exit(1)

# -----------------------------
# Utilitaires
# -----------------------------
def dur_audio(p: pathlib.Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error","-show_entries","format=duration",
            "-of","default=nk=1:nw=1", str(p)
        ], stderr=subprocess.DEVNULL).decode("utf-8","ignore").strip()
        return float(out)
    except Exception:
        return 0.0

def to_ass_ts(sec: float) -> str:
    if sec < 0: sec = 0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

def split_sentences(txt: str) -> list[str]:
    # Nettoyage simple + suppression didascalies entre [ ] ou ( )
    s = re.sub(r"\[[^\]]+\]", "", txt)
    s = re.sub(r"\([^)]+\)", "", s)
    s = re.sub(r"\s+", " ", s.strip())
    # Coupe après . ! ? … (en gardant la ponctuation dans la phrase)
    return [p.strip() for p in re.split(r'(?<=[\.\!\?…])\s+', s) if p.strip()]

def wrap_sentence(sentence: str, max_words=4, max_lines=3) -> str:
    """
    Retourne la phrase repliée sur 2–3 lignes max, 4 mots max/ligne,
    en séparant les lignes ASS avec \N (sans backslash superflu).
    """
    words = sentence.split()
    lines: list[list[str]] = []
    for w in words:
        if not lines or len(lines[-1]) >= max_words:
            if len(lines) >= max_lines:
                # si on dépasse, on ajoute sur la dernière ligne
                lines[-1].append(w)
            else:
                lines.append([w])
        else:
            lines[-1].append(w)
    # IMPORTANT: utiliser \N tel quel (pas d'échappement Python supplémentaire)
    return r"\N".join(" ".join(line) for line in lines)

# -----------------------------
# Lecture transcript & audio
# -----------------------------
raw = tpath.read_text(encoding="utf-8")
audio_dur = max(0.01, dur_audio(apath))

sentences = split_sentences(raw)
if not sentences:
    sentences = [raw]

# -----------------------------
# Répartition temporelle
# -----------------------------
lead  = float(args.lead)
speed = float(args.speed) if args.speed else 1.0

start_t = max(0.0, lead)
eff_dur = max(0.0, (audio_dur - start_t) / (speed if speed != 0 else 1.0))

total_chars = sum(len(s) for s in sentences) or 1
min_seg = 0.8  # durée mini par phrase (ajustable)
events = []
t = start_t
for snt in sentences:
    share = eff_dur * (len(snt) / total_chars)
    seg = max(min_seg, share)
    s = t
    e = min(start_t + eff_dur, t + seg)
    txt = wrap_sentence(snt, max_words=args.max_words, max_lines=args.max_lines)
    events.append((s, e, txt))
    t = e

# Force la dernière phrase à la fin de l'audio
if events:
    s, _, txt = events[-1]
    events[-1] = (s, audio_dur, txt)

# -----------------------------
# Header ASS + écriture
# -----------------------------
hdr = (
f"[Script Info]\n"
f"ScriptType: v4.00+\n"
f"PlayResX: 1080\n"
f"PlayResY: 1920\n"
f"WrapStyle: 2\n"
f"ScaledBorderAndShadow: yes\n"
f"YCbCr Matrix: TV.709\n"
f"\n"
f"[V4+ Styles]\n"
f"Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
f"Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
f"Alignment, MarginL, MarginR, MarginV, Encoding\n"
f"Style: TikTok,{args.font},{args.size},{args.colour},&H00000000,{args.outline_colour},{args.back_colour},"
f"0,0,0,0,100,100,0,0,1,{args.outline},{args.shadow},{args.align},40,40,{args.marginv},1\n"
f"\n"
f"[Events]\n"
f"Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
)

with opath.open("w", encoding="utf-8") as f:
    f.write(hdr)
    for s, e, txt in events:
        # NOTE: on écrit txt tel quel (contient \N pour les retours à la ligne ASS)
        f.write(f"Dialogue: 0,{to_ass_ts(s)},{to_ass_ts(e)},TikTok,,0,0,0,,{txt}\n")

print(f"[build_ass] écrit: {opath} (durée audio détectée: {audio_dur:.2f}s)")