#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, argparse, pathlib, subprocess, re, json

# ==========================
# Arguments CLI
# ==========================
ap = argparse.ArgumentParser(
    description="Build ASS subtitles (title/story/cta) calés sur un timeline JSON, avec wrap et anti-dérive."
)

ap.add_argument("--transcript", required=True, help="Histoire (UTF-8).")
ap.add_argument("--audio", required=True, help="Audio narratif (voice.wav) pour fallback durées.")
ap.add_argument("--out", default="subs/captions.ass", help="Sortie ASS.")

# Titre / CTA (facultatif si déjà fournis ailleurs)
ap.add_argument("--title-text", default=None, help="Texte du titre (sinon story/title.txt si présent).")
ap.add_argument("--cta-text", default=None, help="Texte CTA (sinon story/cta.txt si présent).")

# Timeline
ap.add_argument("--timeline", default="audio/timeline.json", help="JSON avec segments title/story/cta.")
ap.add_argument("--gap-before-cta", type=float, default=1.0, help="Marge minimale (s) entre fin story et début CTA.")

# Styles généraux (story)
ap.add_argument("--font", default="Arial")
ap.add_argument("--size", type=int, default=80)
ap.add_argument("--colour", default="&H00FFFF00")         # jaune
ap.add_argument("--outline-colour", default="&H00000000") # noir
ap.add_argument("--back-colour", default="&H64000000")    # semi-noir
ap.add_argument("--outline", type=float, default=3.0)
ap.add_argument("--shadow", type=float, default=2.0)
ap.add_argument("--align", type=int, default=5)           # centre
ap.add_argument("--marginv", type=int, default=200)

# Titre
ap.add_argument("--title-font", default=None)
ap.add_argument("--title-size", type=int, default=90)
ap.add_argument("--title-colour", default="&H00FFFF00")
ap.add_argument("--title-align", type=int, default=5)
ap.add_argument("--title-marginv", type=int, default=600)
ap.add_argument("--title-max-words", type=int, default=4)

# CTA
ap.add_argument("--cta-font", default=None)
ap.add_argument("--cta-size", type=int, default=80)
ap.add_argument("--cta-colour", default="&H00FFFF00")
ap.add_argument("--cta-align", type=int, default=5)
ap.add_argument("--cta-marginv", type=int, default=600)
ap.add_argument("--cta-max-words", type=int, default=4)

# Story wrap
ap.add_argument("--story-max-words-per-line", type=int, default=4)
ap.add_argument("--story-max-lines", type=int, default=4)

# Ajustements globaux
ap.add_argument("--lead", type=float, default=0.0, help="Décalage global (s).")
ap.add_argument("--speed", type=float, default=1.0, help="Facteur global vitesses.")

args = ap.parse_args()

# ==========================
# Utilitaires
# ==========================
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
    cs = int(round((sec - int(sec)) * 100))  # centisecondes
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

def clean_text(s: str) -> str:
    s = re.sub(r"\[[^\]]*\]", " ", s)
    s = re.sub(r"\([^)]+\)", " ", s)
    s = re.sub(r"^(?:voix|narrateur|speaker)\s*\d*\s*:\s*", "", s,
               flags=re.IGNORECASE|re.MULTILINE)
    s = re.sub(r"\{[^}]*\}", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def split_sentences(s: str):
    parts = re.split(r"([\.!\?;:…])", s)
    out = []
    for i in range(0, len(parts), 2):
        seg = parts[i].strip()
        punct = parts[i+1] if i+1 < len(parts) else ""
        if not seg: continue
        sent = (seg + punct).strip()
        if sent: out.append(sent)
    return out

def wrap_words(text: str, max_words: int) -> list:
    ws = text.split()
    return [" ".join(ws[i:i+max_words]) for i in range(0, len(ws), max_words)]

def words_count(lines: list) -> int:
    return sum(len(l.split()) for l in lines)

def sanitize_ass_text(txt: str) -> str:
    return re.sub(r"\{[^}]*\}", "", txt)

# ==========================
# E/S fichiers
# ==========================
tpath = pathlib.Path(args.transcript)
apath = pathlib.Path(args.audio)
opath = pathlib.Path(args.out)
opath.parent.mkdir(parents=True, exist_ok=True)

if not tpath.exists() or not tpath.stat().st_size:
    print("[build_ass] Transcript introuvable/vide:", tpath, file=sys.stderr); sys.exit(1)
if not apath.exists() or not apath.stat().st_size:
    print("[build_ass] Audio introuvable/vide:", apath, file=sys.stderr); sys.exit(1)

title_txt = args.title_text
if title_txt is None:
    p = pathlib.Path("story/title.txt")
    if p.exists() and p.stat().st_size:
        title_txt = p.read_text(encoding="utf-8").strip()

cta_txt = args.cta_text
if cta_txt is None:
    p = pathlib.Path("story/cta.txt")
    if p.exists() and p.stat().st_size:
        cta_txt = p.read_text(encoding="utf-8").strip()

story_raw = clean_text(tpath.read_text(encoding="utf-8", errors="ignore"))
audio_dur = max(0.01, ffprobe_duration(apath))

# ==========================
# Timeline parsing (robuste)
# ==========================
def read_timeline(tl_path: pathlib.Path):
    if not tl_path.exists() or not tl_path.stat().st_size:
        return None
    try:
        data = json.loads(tl_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    result = {"title": None, "story": None, "cta": None}
    if isinstance(data, dict):
        for k in ("title","story","cta"):
            if isinstance(data.get(k), dict):
                st = float(data[k].get("start", 0.0))
                en = float(data[k].get("end", 0.0))
                if en > st:
                    result[k] = (st, en)
    elif isinstance(data, list):
        for it in data:
            if not isinstance(it, dict): continue
            nm = str(it.get("name","")).lower()
            st = it.get("start", None)
            en = it.get("end", None)
            if nm in ("title","story","cta") and isinstance(st,(int,float)) and isinstance(en,(int,float)) and en>st:
                result[nm] = (float(st), float(en))
    return result

timeline = read_timeline(pathlib.Path(args.timeline))

if timeline is None:
    # Fallback heuristique
    print("[build_ass] Avertissement: timeline absente/illisible, fallback heuristique.", file=sys.stderr)
    title_win = (0.0, min(3.0, audio_dur*0.06)) if title_txt else None
    cta_win = (max(audio_dur-4.0, 0.0), audio_dur) if cta_txt else None
    story_start = (title_win[1] if title_win else 0.0)
    story_end = (cta_win[0] if cta_win else audio_dur)
    story_win = (story_start, max(story_start, story_end))
else:
    title_win = timeline.get("title")
    story_win = timeline.get("story")
    cta_win   = timeline.get("cta")

# ---- Correction propre du gap avant CTA ----
if story_win and cta_win:
    gap = max(0.0, args.gap_before_cta)
    if gap > 0.0 and cta_win[0] < story_win[1] + gap:
        cta_dur = max(0.0, cta_win[1] - cta_win[0])
        new_start = story_win[1] + gap
        cta_win = (new_start, min(new_start + cta_dur, audio_dur))

# ==========================
# Génération événements
# ==========================
events = []

def append_block_lines(win, lines, style_name):
    """Répartit la fenêtre win (start,end) proportionnellement au nb de mots par bloc."""
    if not win or not lines:
        return
    st, en = win
    st = max(0.0, st)
    en = min(en, audio_dur)
    if en <= st:
        return

    # story: pack par N lignes ; title/cta: tout d’un coup
    if style_name == "TikTok":
        block_size = max(1, args.story_max_lines)
    else:
        block_size = len(lines)

    blocks = []
    for i in range(0, len(lines), block_size):
        blocks.append(lines[i:i+block_size])

    tot_words = sum(words_count(b) for b in blocks) or len(blocks)
    seg_dur = en - st
    t = st
    for j, blk in enumerate(blocks):
        bw = words_count(blk) or 1
        dur = seg_dur * (bw / tot_words)
        s = t
        e = st + seg_dur if j == len(blocks)-1 else (t + dur)
        txt = r"\N".join(blk)
        txt = sanitize_ass_text(txt)
        events.append((s, e, style_name, txt))
        t = e

def make_lines_from_title(txt):
    txt = clean_text(txt or "")
    return wrap_words(txt, max(1, args.title_max_words))

def make_lines_from_cta(txt):
    txt = clean_text(txt or "")
    return wrap_words(txt, max(1, args.cta_max_words))

def make_lines_from_story(txt):
    txt = clean_text(txt or "")
    sents = split_sentences(txt)
    lines = []
    for s in sents:
        lines.extend(wrap_words(s, max(1, args.story_max_words_per_line)))
    return lines

# Titre
if title_txt and title_win:
    t_lines = make_lines_from_title(title_txt)
    append_block_lines(title_win, t_lines, "Title")

# Story
if story_win:
    s_lines = make_lines_from_story(story_raw)
    if not s_lines:
        s_lines = [story_raw]
    append_block_lines(story_win, s_lines, "TikTok")

# CTA
if cta_txt and cta_win:
    c_lines = make_lines_from_cta(cta_txt)
    append_block_lines(cta_win, c_lines, "CTA")

# Ajustements globaux lead/speed
def adj_pair(s, e):
    s2 = max(0.0, args.lead + s * args.speed)
    e2 = max(0.0, args.lead + e * args.speed)
    return (max(0.0, min(s2, audio_dur)), max(0.0, min(e2, audio_dur)))

events = [(*adj_pair(s,e), st, txt) for (s,e,st,txt) in events]
events.sort(key=lambda x: (x[0], x[1]))

# ==========================
# Header ASS (3 styles)
# ==========================
title_font = args.title_font or args.font
cta_font   = args.cta_font   or args.font

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
    f"Style: Title,{title_font},{args.title_size},{args.title_colour},&H00000000,{args.outline_colour},{args.back_colour},"
    f"0,0,0,0,100,100,0,0,1,{args.outline},{args.shadow},{args.title_align},40,40,{args.title_marginv},1\n"
    f"Style: CTA,{cta_font},{args.cta_size},{args.cta_colour},&H00000000,{args.outline_colour},{args.back_colour},"
    f"0,0,0,0,100,100,0,0,1,{args.outline},{args.shadow},{args.cta_align},40,40,{args.cta_marginv},1\n"
    "\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
)

# ==========================
# Écriture
# ==========================
opath.parent.mkdir(parents=True, exist_ok=True)
with opath.open("w", encoding="utf-8") as f:
    f.write(hdr)
    for s, e, sty, txt in events:
        f.write(f"Dialogue: 0,{to_ass_ts(s)},{to_ass_ts(e)},{sty},,0,0,0,,{txt}\n")

print(f"[build_ass] écrit: {opath} | events={len(events)} | audio_dur={audio_dur:.2f}s")