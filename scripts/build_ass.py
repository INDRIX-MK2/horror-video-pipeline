#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, argparse, pathlib, subprocess, re, json

# -----------------------------
# CLI
# -----------------------------
ap = argparse.ArgumentParser(
    description="Génère un .ass centré (titre + histoire + cta), phrase par phrase avec wrap multi-lignes."
)
ap.add_argument("--transcript", required=True, help="Fichier texte de la narration (histoire).")
ap.add_argument("--audio",      required=True, help="Fichier audio (wav/mp3) pour caler la durée totale.")
ap.add_argument("--out",        default="subs/captions.ass", help="Chemin de sortie .ass")

# Optionnels : titre / cta / timeline
ap.add_argument("--title-file", default=None, help="Fichier texte du titre (optionnel).")
ap.add_argument("--cta-file",   default=None, help="Fichier texte du CTA (optionnel).")
ap.add_argument("--timeline",   default=None, help="JSON avec segments {title:{start,end}, story:{...}, cta:{...}}.")

# Style ASS (modifiables à la volée)
ap.add_argument("--font",   default="Arial")
ap.add_argument("--size",   type=int, default=80)
ap.add_argument("--colour", default="&H00FFFF00")  # Jaune (AABBGGRR)
ap.add_argument("--outline-colour", dest="outline_colour", default="&H00000000")
ap.add_argument("--back-colour",    dest="back_colour",    default="&H64000000")
ap.add_argument("--outline", type=int, default=3)
ap.add_argument("--shadow",  type=int, default=2)
ap.add_argument("--align",   type=int, default=5)  # 5 = centre milieu
ap.add_argument("--marginv", type=int, default=200)

# Contrôle du rendu des lignes de l'histoire
ap.add_argument("--max-words", type=int, default=4, help="Mots max par ligne (histoire).")
ap.add_argument("--max-lines", type=int, default=3, help="Lignes max par phrase (histoire).")

# Anti-dérive simple quand pas de timeline
ap.add_argument("--lead",  type=float, default=0.0, help="Décalage initial (s) si pas de timeline.")
ap.add_argument("--speed", type=float, default=1.2, help="Vitesse (>1 accélère, <1 ralentit) si pas de timeline.")

args = ap.parse_args()

tpath = pathlib.Path(args.transcript)
apath = pathlib.Path(args.audio)
opath = pathlib.Path(args.out)
opath.parent.mkdir(parents=True, exist_ok=True)

if not tpath.exists() or not tpath.stat().st_size:
    print("Transcript introuvable/vide", file=sys.stderr); sys.exit(1)
if not apath.exists() or not apath.stat().st_size:
    print("Audio introuvable/vide", file=sys.stderr); sys.exit(1)

title_txt = ""
if args.title_file:
    tp = pathlib.Path(args.title_file)
    if tp.exists() and tp.stat().st_size:
        title_txt = tp.read_text(encoding="utf-8").strip()

cta_txt = ""
if args.cta_file:
    cp = pathlib.Path(args.cta_file)
    if cp.exists() and cp.stat().st_size:
        cta_txt = cp.read_text(encoding="utf-8").strip()

timeline = None
if args.timeline:
    jp = pathlib.Path(args.timeline)
    if jp.exists() and jp.stat().st_size:
        try:
            timeline = json.loads(jp.read_text(encoding="utf-8"))
        except Exception:
            timeline = None

# -----------------------------
# Utilitaires
# -----------------------------
def dur_audio(p: pathlib.Path) -> float:
    try:
        out = subprocess.check_output(
            ["ffprobe","-v","error","-show_entries","format=duration","-of","default=nk=1:nw=1", str(p)],
            stderr=subprocess.DEVNULL
        ).decode("utf-8","ignore").strip()
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
    # Coupe après . ! ? …
    return [p.strip() for p in re.split(r'(?<=[\.\!\?…])\s+', s) if p.strip()]

def wrap_sentence(sentence: str, max_words=4, max_lines=3) -> str:
    # Retourne une seule chaîne avec séparateurs ASS \N entre lignes.
    # IMPORTANT: on écrit "\\N" dans Python pour produire \N dans le .ass.
    words = sentence.split()
    lines = []
    for w in words:
        if not lines or len(lines[-1]) >= max_words:
            if len(lines) >= max_lines:
                lines[-1].append(w)
            else:
                lines.append([w])
        else:
            lines[-1].append(w)
    return "\\N".join(" ".join(line) for line in lines)

# -----------------------------
# Lecture transcript & audio
# -----------------------------
raw_story = tpath.read_text(encoding="utf-8")
audio_dur  = max(0.01, dur_audio(apath))

# -----------------------------
# Segments temporels (timeline si dispo)
# -----------------------------
def tl_seg(name: str, default_start: float, default_end: float):
    if not timeline or not isinstance(timeline, dict) or name not in timeline:
        return (default_start, default_end)
    obj = timeline.get(name)
    # tolère {start:.., end:..} ou [start, end]
    if isinstance(obj, dict):
        st = float(obj.get("start", default_start))
        en = float(obj.get("end",   default_end))
        return (max(0.0, st), max(max(0.0, st), en))
    if isinstance(obj, (list, tuple)) and len(obj) >= 2:
        st = float(obj[0]); en = float(obj[1])
        return (max(0.0, st), max(max(0.0, st), en))
    return (default_start, default_end)

events = []  # (start, end, text)

if timeline:
    # 1) Titre
    if title_txt:
        s, e = tl_seg("title", 0.0, min(2.0, audio_dur))
        txt = wrap_sentence(title_txt, max_words=4, max_lines=2)
        events.append((s, min(e, audio_dur), txt))
    # 2) Story
    story_s, story_e = tl_seg("story", 0.0, audio_dur)
    story_s = max(0.0, story_s); story_e = min(audio_dur, story_e)
    sentences = split_sentences(raw_story)
    if not sentences:
        sentences = [raw_story.strip()]
    total_chars = sum(len(s) for s in sentences) or 1
    dur_story = max(0.0, story_e - story_s)
    min_seg = 0.5
    t = story_s
    for snt in sentences:
        share = dur_story * (len(snt) / total_chars)
        seg = max(min_seg, share)
        start = t
        end   = min(story_e, t + seg)
        txt = wrap_sentence(snt, max_words=args.max_words, max_lines=args.max_lines)
        events.append((start, end, txt))
        t = end
    # 3) CTA
    if cta_txt:
        s, e = tl_seg("cta", audio_dur-2.0, audio_dur)
        s = max(0.0, s); e = min(audio_dur, e)
        txt = wrap_sentence(cta_txt, max_words=4, max_lines=2)
        events.append((s, e, txt))

else:
    # Pas de timeline => découpage heuristique
    lead  = float(args.lead)
    speed = float(args.speed) if args.speed else 1.0
    start_t = max(0.0, lead)
    eff_dur = max(0.0, (audio_dur - start_t) / (speed if speed != 0 else 1.0))

    t = start_t
    if title_txt:
        title_d = min(2.0, max(1.0, 0.03 * eff_dur))
        txt = wrap_sentence(title_txt, max_words=4, max_lines=2)
        events.append((t, min(t + title_d, audio_dur), txt))
        t += title_d

    sentences = split_sentences(raw_story)
    if not sentences:
        sentences = [raw_story.strip()]
    leftover = max(0.0, audio_dur - t - (2.0 if cta_txt else 0.0))
    total_chars = sum(len(s) for s in sentences) or 1
    min_seg = 0.8
    for snt in sentences:
        share = leftover * (len(snt) / total_chars)
        seg = max(min_seg, share)
        s = t
        e = min(audio_dur, t + seg)
        txt = wrap_sentence(snt, max_words=args.max_words, max_lines=args.max_lines)
        events.append((s, e, txt))
        t = e

    if cta_txt and t < audio_dur:
        cta_d = min(2.0, audio_dur - t)
        if cta_d > 0.05:
            txt = wrap_sentence(cta_txt, max_words=4, max_lines=2)
            events.append((t, min(t + cta_d, audio_dur), txt))
            t += cta_d

# Nettoyage et garde-fous
cleaned = []
for (s, e, txt) in events:
    s = max(0.0, min(s, audio_dur))
    e = max(s, min(e, audio_dur))
    if e - s > 0.02 and txt:
        cleaned.append((s, e, txt))

events = sorted(cleaned, key=lambda x: (x[0], x[1]))

# -----------------------------
# Header ASS + écriture
# -----------------------------
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
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
    "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
    "Alignment, MarginL, MarginR, MarginV, Encoding\n"
    f"Style: TikTok,{args.font},{args.size},{args.colour},&H00000000,"
    f"{args.outline_colour},{args.back_colour},0,0,0,0,100,100,0,0,1,"
    f"{args.outline},{args.shadow},{args.align},40,40,{args.marginv},1\n"
    "\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
)

with opath.open("w", encoding="utf-8") as f:
    f.write(hdr)
    for s, e, txt in events:
        f.write(f"Dialogue: 0,{to_ass_ts(s)},{to_ass_ts(e)},TikTok,,0,0,0,,{txt}\n")

print(f"[build_ass] écrit: {opath} (durée audio détectée: {audio_dur:.2f}s)")