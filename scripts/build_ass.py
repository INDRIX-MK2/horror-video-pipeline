#!/usr/bin/env python3
import argparse, pathlib, json, subprocess, sys, re
from typing import List, Tuple, Optional, Dict, Any

# -----------------------------
# Utilitaires
# -----------------------------
def ffprobe_duration(path: pathlib.Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error",
            "-show_entries","format=duration",
            "-of","default=nk=1:nw=1",
            str(path)
        ]).decode("utf-8","ignore").strip()
        return float(out)
    except Exception:
        return 0.0

def clean_text(s: str) -> str:
    # Nettoyage léger : retirer crochets/parenthèses (didascalies éventuelles),
    # enlever { } qui seraient interprétés par ASS, normaliser espaces
    s = re.sub(r"\[[^\]]+\]", " ", s)
    s = re.sub(r"\([^)]+\)", " ", s)
    s = s.replace("{","(").replace("}",")")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def split_words_lines(text: str, max_words: int) -> List[str]:
    words = text.split()
    lines, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= max_words:
            lines.append(" ".join(cur)); cur=[]
    if cur:
        lines.append(" ".join(cur))
    return lines

def pack_lines_to_events(lines: List[str], max_lines: int) -> List[str]:
    # Regroupe des lignes en “blocs” de sous-titres (1..max_lines lignes par Dialogue)
    blocks, buf = [], []
    for ln in lines:
        buf.append(ln)
        if len(buf) >= max_lines:
            blocks.append("\\N".join(buf)); buf=[]
    if buf:
        blocks.append("\\N".join(buf))
    return blocks

def to_ass_ts(sec: float) -> str:
    if sec < 0: sec = 0.0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

def read_txt(path: Optional[pathlib.Path]) -> str:
    if not path: return ""
    if not path.exists() or path.stat().st_size == 0: return ""
    return path.read_text(encoding="utf-8", errors="ignore")

# -----------------------------
# Timeline
# -----------------------------
def load_timeline(path: Optional[pathlib.Path]) -> List[Dict[str,Any]]:
    if not path or not path.exists() or path.stat().st_size == 0:
        return []
    try:
        j = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(j, dict):
            segs = j.get("segments", [])
        elif isinstance(j, list):
            segs = j
        else:
            segs = []
        out = []
        for obj in segs:
            if not isinstance(obj, dict): 
                continue
            name  = str(obj.get("name","")).strip().lower()
            start = obj.get("start", None)
            end   = obj.get("end", None)
            if isinstance(start,(int,float)) and isinstance(end,(int,float)) and end > start:
                out.append({"name":name,"start":float(start),"end":float(end)})
        return out
    except Exception:
        return []

def seg_lookup(segs: List[Dict[str,Any]], name: str) -> Optional[Tuple[float,float]]:
    n = name.strip().lower()
    for obj in segs:
        if obj.get("name","").lower() == n:
            return float(obj["start"]), float(obj["end"])
    return None

# -----------------------------
# Script principal
# -----------------------------
ap = argparse.ArgumentParser(description="Build ASS (titre + histoire + cta) à partir d'une timeline")
ap.add_argument("--transcript", required=True, help="Texte de l'histoire (story.txt)")
ap.add_argument("--title-file", help="Titre (title.txt)")
ap.add_argument("--cta-file",   help="CTA (cta.txt)")
ap.add_argument("--timeline",   help="Timeline JSON (audio/timeline.json)")
ap.add_argument("--audio",      help="Audio complet (optionnel, pour logs/contrôles)")
ap.add_argument("--out", default="subs/captions.ass")

# Style commun (modifiable facilement dans le workflow)
ap.add_argument("--font", default="Arial")
ap.add_argument("--size", type=int, default=80)
ap.add_argument("--colour", default="&H00FFFF00")            # jaune pur (ASS = AABBGGRR)
ap.add_argument("--outline-colour", dest="outline_colour", default="&H00000000")
ap.add_argument("--back-colour",    dest="back_colour",    default="&H64000000")
ap.add_argument("--outline", type=int, default=3)
ap.add_argument("--shadow",  type=int, default=2)
ap.add_argument("--align",   type=int, default=5)           # centre
ap.add_argument("--marginv", type=int, default=200)

# Paramétrage du découpage texte
ap.add_argument("--max-words", type=int, default=4, help="mots par ligne (story)")
ap.add_argument("--max-lines", type=int, default=4, help="lignes max par sous-titre (story)")
ap.add_argument("--lead", type=float, default=0.00, help="avance/retard global story (s)")
ap.add_argument("--speed", type=float, default=1.20, help=">1 accélère l’enchaînement des blocs story")

# Paramètres titre/cta (simple : 1 bloc multi-lignes)
ap.add_argument("--title-max-words", type=int, default=4)
ap.add_argument("--cta-max-words",   type=int, default=4)

args = ap.parse_args()

t_story = pathlib.Path(args.transcript)
t_title = pathlib.Path(args.title_file) if args.title_file else None
t_cta   = pathlib.Path(args.cta_file)   if args.cta_file   else None
timeline_path = pathlib.Path(args.timeline) if args.timeline else None
out_path = pathlib.Path(args.out)
out_path.parent.mkdir(parents=True, exist_ok=True)

story_txt = clean_text(read_txt(t_story))
if not story_txt:
    print("Story (transcript) manquant ou vide.", file=sys.stderr)
    sys.exit(1)

title_txt = clean_text(read_txt(t_title)) if t_title else ""
cta_txt   = clean_text(read_txt(t_cta))   if t_cta   else ""

segs = load_timeline(timeline_path)

def safe_seg(name: str, fallback_dur: float=0.0, start_hint: float=0.0) -> Tuple[float,float]:
    """Retourne (start,end) pour 'name' depuis la timeline, sinon fallback."""
    got = seg_lookup(segs, name)
    if got: 
        return got
    # fallback simple : [start_hint, start_hint+fallback_dur]
    return (start_hint, start_hint + max(0.0, fallback_dur))

# Si pas de timeline, on essaie un fallback grossier avec les durées des WAV connus.
title_d = ffprobe_duration(pathlib.Path("audio/title.wav")) if pathlib.Path("audio/title.wav").exists() else 0.0
story_d = ffprobe_duration(pathlib.Path("audio/story.wav")) if pathlib.Path("audio/story.wav").exists() else 0.0
cta_d   = ffprobe_duration(pathlib.Path("audio/cta.wav"))   if pathlib.Path("audio/cta.wav").exists()   else 0.0

t0 = 0.0
t0_title, t1_title = safe_seg("title", title_d, t0)
t0_story, t1_story = safe_seg("story", story_d, t1_title + 1.0)   # +1s gap par défaut si absent
t0_cta,   t1_cta   = safe_seg("cta",   cta_d,   t1_story + 1.0)

# -----------------------------
# Construire les événements
# -----------------------------
events: List[Tuple[float,float,str]] = []

# TITRE : un seul Dialogue multi-lignes (4 mots max par ligne)
if title_txt and t1_title > t0_title:
    lines = split_words_lines(title_txt, args.title_max_words)
    text_block = "\\N".join(lines)
    events.append((t0_title, t1_title, text_block))

# STORY : paquetage en blocs (max_lines), répartis sur [t0_story, t1_story]
if story_txt and t1_story > t0_story:
    story_lines = split_words_lines(story_txt, args.max_words)
    story_blocks = pack_lines_to_events(story_lines, args.max_lines)
    n = max(1, len(story_blocks))
    dur = max(0.01, (t1_story - t0_story))
    per = (dur / n) / max(0.01, args.speed)
    t = t0_story + args.lead
    for block in story_blocks:
        s = max(t0_story, t)
        e = min(t1_story, s + per)
        if e - s > 0.01:
            events.append((s, e, block))
        t = e

# CTA : un seul Dialogue multi-lignes (4 mots max par ligne)
if cta_txt and t1_cta > t0_cta:
    lines = split_words_lines(cta_txt, args.cta_max_words)
    text_block = "\\N".join(lines)
    events.append((t0_cta, t1_cta, text_block))

# Vérif
events = [ev for ev in events if ev[1] > ev[0]]
if not events:
    print("Aucun évènement de sous-titres généré (vérifie timeline et textes).", file=sys.stderr)
    sys.exit(2)

events.sort(key=lambda x: x[0])

# -----------------------------
# Écriture ASS
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
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
    "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
    "Alignment, MarginL, MarginR, MarginV, Encoding\n"
    f"Style: TikTok,{args.font},{args.size},{args.colour},&H00000000,{args.outline_colour},{args.back_colour},"
    f"0,0,0,0,100,100,0,0,1,{args.outline},{args.shadow},{args.align},40,40,{args.marginv},1\n"
    "\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
)

with out_path.open("w", encoding="utf-8") as f:
    f.write(hdr)
    for s,e,text in events:
        # Sécurité : pas de trailing backslash; \\N déjà inséré pour les retours ligne
        txt = text.replace("\\", "\\\\")
        f.write(f"Dialogue: 0,{to_ass_ts(s)},{to_ass_ts(e)},TikTok,,0,0,0,,{txt}\n")

print(f"[build_ass] écrit: {out_path} | events={len(events)} | "
      f"title=[{t0_title:.2f},{t1_title:.2f}] story=[{t0_story:.2f},{t1_story:.2f}] cta=[{t0_cta:.2f},{t1_cta:.2f}]")