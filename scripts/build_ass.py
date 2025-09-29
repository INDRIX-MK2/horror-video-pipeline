#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, argparse, pathlib, subprocess, re, json, math

# ---------- Arguments ----------
ap = argparse.ArgumentParser(description="Construit un .ass avec Histoire + (optionnel) Titre & CTA centrés")
ap.add_argument("--transcript", required=True, help="Texte de l'histoire (sans didascalies)")
ap.add_argument("--audio", required=True, help="Audio final (voice.wav) pour durée de secours")
ap.add_argument("--out", default="subs/captions.ass", help="Fichier .ass de sortie")

# Styles / mise en page histoire
ap.add_argument("--font", default="Arial")
ap.add_argument("--size", type=int, default=60)           # taille par défaut des sous-titres
ap.add_argument("--max-words", type=int, default=5)       # ~mots/ligne
ap.add_argument("--max-lines", type=int, default=3)       # lignes max par event
ap.add_argument("--align", type=int, default=2)           # 2 = bas centré (TikTok)
ap.add_argument("--margin-v", type=int, default=200)      # marge verticale

# Anti-dérive (si besoin)
ap.add_argument("--lead", type=float, default=0.0, help="Décalage d'avance (sec)")
ap.add_argument("--speed", type=float, default=1.0, help="Facteur vitesse lecture (1.0 = normal)")

# Titre & CTA (optionnels)
ap.add_argument("--title", help="story/title.txt")
ap.add_argument("--cta", help="story/cta.txt")
ap.add_argument("--timeline", help="audio/timeline.json (durées: title,gap,story,cta,total)")

# Style titre/cta
ap.add_argument("--title-size", type=int, default=80)
ap.add_argument("--cta-size", type=int, default=72)
args = ap.parse_args()

tpath = pathlib.Path(args.transcript)
apath = pathlib.Path(args.audio)
opath = pathlib.Path(args.out)
opath.parent.mkdir(parents=True, exist_ok=True)

def die(msg):
    print(msg, file=sys.stderr); sys.exit(1)

if not tpath.exists() or not tpath.stat().st_size:
    die("Transcript introuvable/vide")
if not apath.exists() or not apath.stat().st_size:
    die("Audio introuvable/vide")

def dur_audio(p):
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error","-show_entries","format=duration",
            "-of","default=nk=1:nw=1", str(p)
        ]).decode("utf-8","ignore").strip()
        return float(out)
    except Exception:
        return 0.0

def to_ass_ts(sec):
    if sec < 0: sec = 0.0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

def clean_text(s: str) -> str:
    # supprime didascalies simples entre [] ou ()
    s = re.sub(r"\[[^\]]+\]", "", s)
    s = re.sub(r"\([^)]+\)", "", s)
    return s.strip()

def wrap_words_to_lines(text: str, max_words=5, max_lines=3):
    # coupe en mots puis regroupe ~max_words par ligne (2-3 lignes)
    words = text.split()
    lines, buf = [], []
    for w in words:
        buf.append(w)
        if len(buf) >= max_words:
            lines.append(" ".join(buf)); buf = []
            if len(lines) >= max_lines:
                buf = []  # jette le reste si excès
                break
    if buf and len(lines) < max_lines:
        lines.append(" ".join(buf))
    # join avec \N (ASS newline). Aucun "\" seul n'est ajouté.
    return r"\N".join(lines)

def split_story_into_chunks(raw_lines, words_per_line=5, max_lines=3):
    # concat lignes -> mots ; construit des "chunks" (un event = 1 à max_lines lignes)
    words = []
    for ln in raw_lines:
        ln = ln.strip()
        if ln:
            words.extend(ln.split())

    chunks = []
    if not words:
        return chunks

    # un chunk = (max_words * max_lines) mots
    block = words_per_line * max_lines
    i = 0
    while i < len(words):
        part = words[i:i+block]
        i += block
        # subdivise part en lignes
        lines = []
        for j in range(0, len(part), words_per_line):
            lines.append(" ".join(part[j:j+words_per_line]))
        chunks.append(r"\N".join(lines))
    return chunks

# ----- Durées & timeline -----
timeline = {"title":0.0, "gap":0.0, "story":0.0, "cta":0.0, "total":0.0}
if args.timeline:
    jpath = pathlib.Path(args.timeline)
    if jpath.exists() and jpath.stat().st_size:
        try:
            timeline = json.loads(jpath.read_text(encoding="utf-8"))
        except Exception:
            pass

audio_total = dur_audio(apath)
if timeline.get("total", 0.0) <= 0.0:
    timeline["total"] = audio_total

title_d = float(timeline.get("title", 0.0) or 0.0)
gap_d   = float(timeline.get("gap", 0.0) or 0.0)
story_d = float(timeline.get("story", 0.0) or max(0.0, audio_total - (title_d + gap_d + float(timeline.get("cta",0.0)))))
cta_d   = float(timeline.get("cta", 0.0) or 0.0)

t0_story = title_d + gap_d
t1_story = t0_story + story_d
t0_cta   = t1_story
t1_cta   = t0_cta + cta_d

# ----- Charger textes -----
raw_story = clean_text(tpath.read_text(encoding="utf-8"))
story_lines = [ln.strip() for ln in raw_story.splitlines() if ln.strip()]

title_txt = ""
if args.title:
    tp = pathlib.Path(args.title)
    if tp.exists() and tp.stat().st_size:
        title_txt = clean_text(tp.read_text(encoding="utf-8"))

cta_txt = ""
if args.cta:
    cp = pathlib.Path(args.cta)
    if cp.exists() and cp.stat().st_size:
        cta_txt = clean_text(cp.read_text(encoding="utf-8"))

# ----- Construire événements -----
events = []

# 1) Titre centré (si présent)
if title_txt and title_d > 0.05:
    # wrap doux: ~max 10 mots/ligne, 2 lignes max
    title_lines = wrap_words_to_lines(title_txt, max_words=10, max_lines=2)
    events.append({
        "style": "Title",
        "start": 0.0,
        "end": max(0.01, title_d - 0.01),  # s'arrête avant la suite
        "text": title_lines
    })

# 2) Histoire sur [t0_story, t1_story]
story_chunks = split_story_into_chunks(
    story_lines, words_per_line=args.max_words, max_lines=args.max_lines
)
n = max(1, len(story_chunks))
# Durée récit ajustée avec anti-derive
story_span = max(0.0, (t1_story - t0_story) / max(0.001, args.speed))
per = story_span / n
t = t0_story + args.lead
for i, txt in enumerate(story_chunks, start=1):
    s = t
    e = min(t0_story + story_span + args.lead, t + per)
    events.append({"style": "TikTok", "start": s, "end": e, "text": txt})
    t = e

# 3) CTA centré (si présent)
if cta_txt and cta_d > 0.05:
    cta_lines = wrap_words_to_lines(cta_txt, max_words=8, max_lines=2)
    # démarre juste après la dernière ligne "histoire"
    last_story_end = max((ev["end"] for ev in events if ev["style"]=="TikTok"), default=t1_story)
    scta = max(t0_cta, last_story_end)
    ecta = max(scta + 0.2, t1_cta)  # garantit un affichage lisible
    events.append({
        "style": "CTA",
        "start": scta,
        "end": ecta,
        "text": cta_lines
    })

# ----- Header ASS -----
# Couleurs ASS: &HAABBGGRR (AA=alpha, 00=opaque). Jaune fluo = RR=FF, GG=FF, BB=00 => &H00FFFF00
ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTok,{args.font},{args.size},&H00FFFFFF,&H00000000,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,3,2,{args.align},40,40,{args.margin_v},1
Style: Title,{args.font},{args.title_size},&H00FFFF00,&H00000000,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,3,2,5,40,40,40,1
Style: CTA,{args.font},{args.cta_size},&H00FFFF00,&H00000000,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,3,2,5,40,40,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".replace("\r\n","\n")

# ----- Ecriture ASS -----
with opath.open("w", encoding="utf-8") as f:
    f.write(ass_header)
    for ev in events:
        f.write(
            "Dialogue: 0,{},{},{},,0,0,0,,{}\n".format(
                to_ass_ts(ev["start"]),
                to_ass_ts(ev["end"]),
                ev["style"],
                ev["text"]
            )
        )

print(f"[build_ass] écrit: {opath} (timeline: title={title_d:.2f}s, gap={gap_d:.2f}s, story={story_d:.2f}s, cta={cta_d:.2f}s, total={timeline.get('total', audio_total):.2f}s)")