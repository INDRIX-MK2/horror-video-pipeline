#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, argparse, pathlib, json, re, subprocess

# ---------- Utils ----------
def ffprobe_duration(path: pathlib.Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error",
            "-show_entries","format=duration",
            "-of","default=nk=1:nw=1",
            str(path)
        ], stderr=subprocess.DEVNULL).decode("utf-8","ignore").strip()
        return max(0.0, float(out))
    except Exception:
        return 0.0

def ass_ts(sec: float) -> str:
    if sec < 0: sec = 0.0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

def clean_text(t: str) -> str:
    t = re.sub(r"\[[^\]]+\]", " ", t)
    t = re.sub(r"\([^)]+\)", " ", t)
    t = re.sub(r"(?i)\b(voix\s*\d+|narrateur|narratrice)\s*:\s*", " ", t)
    t = t.replace("{","(").replace("}",")")
    t = re.sub(r"\s+"," ", t).strip()
    return t

def split_sentences(text: str):
    txt = clean_text(text)
    parts = re.split(r'(?<=[\.\!\?…])\s+', txt)
    return [p.strip() for p in parts if p.strip()]

def wrap_words(words, max_words=4, max_lines=3):
    """
    Retourne jusqu'à max_lines, avec max_words par ligne.
    On renvoie des lignes destinées à être jointes par '\\N' (sauts durs ASS).
    """
    lines, buf = [], []
    for w in words:
        buf.append(w)
        if len(buf) >= max_words:
            lines.append(" ".join(buf)); buf=[]
        if len(lines) >= max_lines:
            if buf:
                lines[-1] = (lines[-1] + " " + " ".join(buf)).strip()
                buf = []
            break
    if buf and len(lines) < max_lines:
        lines.append(" ".join(buf))
    return lines

def normalize_blocks(durations, total_window):
    total = sum(durations)
    if total <= 0:
        return [0.0 for _ in durations]
    if abs(total - total_window) < 1e-6:
        return durations
    scale = total_window / total
    out = [d * scale for d in durations]
    delta = total_window - sum(out)
    if out:
        out[-1] += delta
    return out

# ---------- Args ----------
ap = argparse.ArgumentParser(description="Build ASS subtitles (Title/Story/CTA) aligned to voice.")
ap.add_argument("--transcript", required=True, help="story/story.txt")
ap.add_argument("--audio",      required=True, help="audio/voice.wav (fallback duration)")
ap.add_argument("--out",        default="subs/captions.ass")

ap.add_argument("--title-file", default="story/title.txt")
ap.add_argument("--cta-file",   default="story/cta.txt")
ap.add_argument("--timeline",   default="audio/timeline.json")  # produit par voice_elevenlabs.py

# Style
ap.add_argument("--font",   default="Arial")
ap.add_argument("--size",   type=int, default=80)
ap.add_argument("--colour", default="&H00FFFF00")          # JAUNE
ap.add_argument("--outline-colour", default="&H00000000")  # contour noir
ap.add_argument("--back-colour",    default="&H64000000")  # fond semi-transparent
ap.add_argument("--outline", type=int, default=3)
ap.add_argument("--shadow",  type=int, default=2)
ap.add_argument("--align",   type=int, default=5)          # centre
ap.add_argument("--marginv", type=int, default=200)

# Tempo / découpage
ap.add_argument("--max-words", type=int, default=3)
ap.add_argument("--max-lines", type=int, default=5)
ap.add_argument("--lead",  type=float, default=0, help="retire n secondes à la fin de chaque event")
ap.add_argument("--speed", type=float, default=1, help=">1.0 = affiche moins longtemps (plus 'speed')")

# Clamps
ap.add_argument("--min-sent", type=float, default=0.80, help="durée min. par phrase")
ap.add_argument("--min-line", type=float, default=0.35, help="durée min. si on divisait (sécurité)")

args = ap.parse_args()

# ---------- Inputs ----------
t_story = pathlib.Path(args.transcript)
t_title = pathlib.Path(args.title_file)
t_cta   = pathlib.Path(args.cta_file)
audio   = pathlib.Path(args.audio)
ass_out = pathlib.Path(args.out)
ass_out.parent.mkdir(parents=True, exist_ok=True)

if not t_story.exists() or t_story.stat().st_size == 0:
    print("Transcript histoire manquant/vide", file=sys.stderr); sys.exit(1)
if not audio.exists() or audio.stat().st_size == 0:
    print("Audio manquant/vide", file=sys.stderr); sys.exit(1)

story_txt = t_story.read_text(encoding="utf-8", errors="ignore")
title_txt = t_title.read_text(encoding="utf-8", errors="ignore") if t_title.exists() else ""
cta_txt   = t_cta.read_text(encoding="utf-8", errors="ignore") if t_cta.exists() else ""

audio_dur = ffprobe_duration(audio)

# ---------- Timeline ----------
tl = None
tline = pathlib.Path(args.timeline)
if tline.exists() and tline.stat().st_size:
    try:
        tl = json.loads(tline.read_text(encoding="utf-8"))
    except Exception:
        tl = None

def seg_of(name, fallback_start, fallback_end):
    if tl and isinstance(tl, dict) and name in tl and isinstance(tl[name], dict):
        st = tl[name].get("start", fallback_start)
        en = tl[name].get("end",   fallback_end)
        if isinstance(st, (int,float)) and isinstance(en, (int,float)) and en > st:
            return float(st), float(en)
    return fallback_start, fallback_end

# Sans timeline: titre dès 0.00, histoire ensuite, CTA à la fin
if not tl:
    title_len = 2.0 if title_txt.strip() else 0.0
    cta_len   = 2.0 if cta_txt.strip()   else 0.0
    title_seg = (0.00, title_len)
    story_seg = (title_len, max(title_len, audio_dur - cta_len))
    cta_seg   = (story_seg[1], audio_dur) if cta_len > 0 else (0.0, 0.0)
else:
    title_seg = seg_of("title", 0.00, 0.00)
    story_seg = seg_of("story", 0.00, audio_dur)
    cta_seg   = seg_of("cta",   0.00, 0.00)

# Petitse sécurité: si le titre commence très près de 0, on le cloue à 0.00
if title_seg[0] < 0.25:
    title_seg = (0.00, title_seg[1])

# ---------- Header ASS ----------
hdr = (
    "[Script Info]\n"
    "ScriptType: v4.00+\n"
    "PlayResX: 1080\n"
    "PlayResY: 1920\n"
    "WrapStyle: 2\n"
    "ScaledBorderAndShadow: yes\n"
    "YCbCr Matrix: TV.709\n\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
    "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
    "Alignment, MarginL, MarginR, MarginV, Encoding\n"
    f"Style: TikTok,{args.font},{args.size},{args.colour},&H00000000,{args.outline_colour},"
    f"{args.back_colour},0,0,0,0,100,100,0,0,1,{args.outline},{args.shadow},{args.align},40,40,{args.marginv},1\n\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
)

events = []

def push_event(start, end, text_lines):
    end_eff = max(start, min(end - args.lead, end))
    if end_eff <= start:
        end_eff = min(end, start + 0.15)
    # IMPORTANT: forcer les sauts de ligne simultanés
    txt = "\\N".join([ln.strip() for ln in text_lines if ln.strip()])
    if not txt:
        return
    events.append(f"Dialogue: 0,{ass_ts(start)},{ass_ts(end_eff)},TikTok,,0,0,0,,{txt}")

# ---------- 1) Title (multi-lignes d'un coup) ----------
if title_txt.strip() and title_seg[1] > title_seg[0]:
    st, en = title_seg
    dur = max(0.8, (en - st) / max(args.speed, 0.01))
    words = clean_text(title_txt).split()
    lines = wrap_words(words, max_words=args.max_words, max_lines=args.max_lines)
    push_event(st, st + dur, lines)

# ---------- 2) Story : phrase par phrase, chaque phrase en multi-lignes ----------
story_sentences = split_sentences(story_txt)
if story_sentences and story_seg[1] > story_seg[0]:
    W = [len(clean_text(s).split()) for s in story_sentences]
    total_w = sum(W) if sum(W) > 0 else len(story_sentences)
    window  = max(0.1, (story_seg[1] - story_seg[0]) / max(args.speed, 0.01))

    raw = [max(args.min_sent, (w / total_w) * window) for w in W]
    dur_sent = normalize_blocks(raw, window)

    t_cursor = story_seg[0]
    for s, d in zip(story_sentences, dur_sent):
        words = clean_text(s).split()
        lines = wrap_words(words, max_words=args.max_words, max_lines=args.max_lines)
        # >>> CORRIGÉ : une seule event multi-lignes pour la phrase
        push_event(t_cursor, t_cursor + d, lines)
        t_cursor += d

# ---------- 3) CTA (multi-lignes d'un coup) ----------
if cta_txt.strip() and cta_seg[1] > cta_seg[0]:
    st, en = cta_seg
    dur = max(0.8, (en - st) / max(args.speed, 0.01))
    words = clean_text(cta_txt).split()
    lines = wrap_words(words, max_words=args.max_words, max_lines=args.max_lines)
    push_event(st, st + dur, lines)

# ---------- Écriture ----------
with open(ass_out, "w", encoding="utf-8") as f:
    f.write(hdr)
    for ev in events:
        f.write(ev + "\n")

if not any("Dialogue:" in ev for ev in events):
    print("[build_ass] Aucun dialogue généré — vérifie title.txt/story.txt/cta.txt et timeline.json.", file=sys.stderr)
    sys.exit(2)

print(f"[build_ass] OK -> {ass_out} (events: {len(events)})")
