#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, argparse, pathlib, json, re, subprocess

# ---------- Utils ----------
def ffprobe_duration(path: pathlib.Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=nk=1:nw=1",
            str(path)
        ], stderr=subprocess.DEVNULL).decode("utf-8", "ignore").strip()
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
    # vire crochets/didascalies et labels de voix
    t = re.sub(r"\[[^\]]+\]", " ", t)
    t = re.sub(r"\([^)]+\)", " ", t)
    t = re.sub(r"(?i)\b(voix\s*\d+|narrateur|narratrice)\s*:\s*", " ", t)
    # évite l'injection d'override ASS
    t = t.replace("{", "(").replace("}", ")")
    # condense espaces
    t = re.sub(r"\s+", " ", t).strip()
    return t

def split_sentences(text: str):
    txt = clean_text(text)
    # coupe par ponctuation forte . ! ? …
    parts = re.split(r'(?<=[\.\!\?…])\s+', txt)
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        return []
    return parts

def wrap_words(words, max_words=4, max_lines=3):
    """Wrap en lignes de <= max_words, tronque au-delà de max_lines si nécessaire (rare)."""
    lines = []
    buf = []
    for w in words:
        buf.append(w)
        if len(buf) >= max_words:
            lines.append(" ".join(buf)); buf = []
        if len(lines) >= max_lines:
            # s'il reste des mots mais on a atteint max_lines, on pousse le reste sur la dernière ligne
            if buf:
                lines[-1] = (lines[-1] + " " + " ".join(buf)).strip()
                buf = []
            break
    if buf and len(lines) < max_lines:
        lines.append(" ".join(buf))
    return lines

def normalize_blocks(durations, total_window):
    """
    Ajuste une liste de durées pour qu'elles tiennent exactement dans total_window,
    en conservant les proportions.
    """
    total = sum(durations)
    if total <= 0:
        return [0 for _ in durations]
    if abs(total - total_window) < 1e-6:
        return durations
    scale = total_window / total
    out = [d * scale for d in durations]
    # petite correction pour l'erreur cumulée
    delta = total_window - sum(out)
    if out:
        out[-1] += delta
    return out

# ---------- Arguments ----------
ap = argparse.ArgumentParser(description="Build ASS subtitles (Titre/Histoire/CTA) calés sur la voix.")
ap.add_argument("--transcript", required=True, help="story/story.txt")
ap.add_argument("--audio", required=True, help="audio/voice.wav (durée de secours)")
ap.add_argument("--out", default="subs/captions.ass")

ap.add_argument("--title-file", default="story/title.txt")
ap.add_argument("--cta-file", default="story/cta.txt")
ap.add_argument("--timeline", default="audio/timeline.json")  # produit par voice_elevenlabs.py

# Style global (modifiable à la volée)
ap.add_argument("--font", default="Arial")
ap.add_argument("--size", type=int, default=80)
ap.add_argument("--colour", default="&H00FFFF00")          # jaune
ap.add_argument("--outline-colour", default="&H00000000")  # contour noir
ap.add_argument("--back-colour", default="&H64000000")     # fond semi-transparent
ap.add_argument("--outline", type=int, default=3)
ap.add_argument("--shadow", type=int, default=2)
ap.add_argument("--align", type=int, default=5)            # centre
ap.add_argument("--marginv", type=int, default=200)

# Découpage/tempo
ap.add_argument("--max-words", type=int, default=4)
ap.add_argument("--max-lines", type=int, default=3)
ap.add_argument("--lead", type=float, default=0.20, help="retire n secondes à la fin de chaque event")
ap.add_argument("--speed", type=float, default=1.20, help=">1.0 = plus court à l’écran")

# Clamps
ap.add_argument("--min-sent", type=float, default=0.80, help="durée min. par phrase (sec)")
ap.add_argument("--min-line", type=float, default=0.35, help="durée min. par ligne (sec)")

args = ap.parse_args()

# ---------- Entrées ----------
root = pathlib.Path(".").resolve()
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
if pathlib.Path(args.timeline).exists() and pathlib.Path(args.timeline).stat().st_size:
    try:
        tl = json.loads(pathlib.Path(args.timeline).read_text(encoding="utf-8"))
    except Exception:
        tl = None

def seg_of(name, fallback_start, fallback_end):
    if tl and isinstance(tl, dict) and name in tl and isinstance(tl[name], dict):
        st = tl[name].get("start", fallback_start)
        en = tl[name].get("end",   fallback_end)
        if isinstance(st, (int, float)) and isinstance(en, (int, float)) and en > st:
            return float(st), float(en)
    return fallback_start, fallback_end

# Fenêtres : si pas de timeline, on répartit grosso modo sur toute la durée
t0 = 0.0
t1 = audio_dur

# heuristique si pas de timeline : 12% titre, 76% story, 12% cta
if not tl:
    title_len = min(3.0, 0.12 * audio_dur) if title_txt.strip() else 0.0
    cta_len   = min(3.0, 0.12 * audio_dur) if cta_txt.strip()   else 0.0
    story_len = max(0.0, audio_dur - title_len - cta_len)
    title_seg = (0.0, title_len)
    story_seg = (title_len, title_len + story_len)
    cta_seg   = (title_len + story_len, audio_dur)
else:
    title_seg = seg_of("title", 0.0, 0.0)
    story_seg = seg_of("story", 0.0, audio_dur)  # à défaut on prend tout
    cta_seg   = seg_of("cta",   0.0, 0.0)

# ---------- Construction ASS ----------
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
    # applique lead et clamp
    e = max(start, min(end - args.lead, end))
    if e <= start:  # garde un minimum pour éviter 0
        e = min(end, start + 0.15)
    # join multi-lignes avec \N (sans backslash final)
    txt = r"\N".join([ln.strip() for ln in text_lines if ln.strip()])
    if not txt:
        return
    events.append(f"Dialogue: 0,{ass_ts(start)},{ass_ts(e)},TikTok,,0,0,0,,{txt}")

# ---- 1) Title
if title_txt.strip() and title_seg[1] > title_seg[0]:
    words = clean_text(title_txt).split()
    lines = wrap_words(words, max_words=args.max_words, max_lines=args.max_lines)
    dur = max(0.5, (title_seg[1] - title_seg[0]) / args.speed)
    push_event(title_seg[0], title_seg[0] + dur, lines)

# ---- 2) Story (par phrases, puis wrap 2–3 lignes)
story_sentences = split_sentences(story_txt)
if story_sentences and story_seg[1] > story_seg[0]:
    W = [len(clean_text(s).split()) for s in story_sentences]
    total_w = sum(W) if sum(W) > 0 else len(story_sentences)
    window = max(0.1, (story_seg[1] - story_seg[0]) / args.speed)

    # durées brutes par phrase (plancher min-sent)
    raw = [max(args.min_sent, (w / total_w) * window) for w in W]
    dur_sent = normalize_blocks(raw, window)

    t_cursor = story_seg[0]
    for s, d in zip(story_sentences, dur_sent):
        words = clean_text(s).split()
        lines = wrap_words(words, max_words=args.max_words, max_lines=args.max_lines)

        # répartir la durée de la phrase entre ses lignes selon #mots
        lw = [len(ln.split()) for ln in lines]
        lw_total = sum(lw) if sum(lw) > 0 else len(lines)
        raw_lines = [max(args.min_line, (w / lw_total) * d) for w in lw]
        dur_lines = normalize_blocks(raw_lines, d)

        start = t_cursor
        for ln, dl in zip(lines, dur_lines):
            push_event(start, start + dl, [ln])
            start += dl
        t_cursor += d

# ---- 3) CTA
if cta_txt.strip() and cta_seg[1] > cta_seg[0]:
    words = clean_text(cta_txt).split()
    lines = wrap_words(words, max_words=args.max_words, max_lines=args.max_lines)
    dur = max(0.5, (cta_seg[1] - cta_seg[0]) / args.speed)
    push_event(cta_seg[0], cta_seg[0] + dur, lines)

# Écriture
with open(ass_out, "w", encoding="utf-8") as f:
    f.write(hdr)
    for ev in events:
        f.write(ev + "\n")

# Sanity check
has_dialogue = any("Dialogue:" in ev for ev in events)
if not has_dialogue:
    print(f"[build_ass] Aucun 'Dialogue:' généré -> vérifie tes fichiers d’entrée et timeline.", file=sys.stderr)
    sys.exit(2)

print(f"[build_ass] OK -> {ass_out} (events: {len(events)})")