#!/usr/bin/env python3
# Génère un .ass simple, robuste (toujours >= 1 Dialogue)
# - Découpe le transcript en phrases, puis wrap en lignes (max_words / max_lines)
# - Calage temporel proportionnel au nb de mots, le tout couvrant (audio_dur / speed)
# - lead: sous-titres apparaissent plus tôt (positif) ou plus tard (négatif)
# - Par défaut: align=5 (centre), couleur jaune, outline noir

import sys, argparse, pathlib, subprocess, re

def dur_audio(p: pathlib.Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error",
            "-show_entries","format=duration",
            "-of","default=nk=1:nw=1", str(p)
        ]).decode("utf-8","ignore").strip()
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

def clean_transcript(raw: str) -> str:
    # Supprimer didascalies et marques (Intro:, Scène:, Voix 1:, Narrateur:, etc.)
    raw = re.sub(r"^\s*(intro|sc[eè]ne|scene|narrateur|voix\s*\d+|cta)\s*:?\s*", "", raw, flags=re.I|re.M)
    # Retirer [brackets] et (parenthèses)
    raw = re.sub(r"\[[^\]]+\]", "", raw)
    raw = re.sub(r"\([^)]+\)", "", raw)
    # Normaliser espaces
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r" *\n+ *", "\n", raw).strip()
    return raw

def split_sentences(text: str):
    # Conserver ponctuation
    parts = re.findall(r"[^.!?…\n]+[.!?…]*", text, flags=re.M)
    sents = [p.strip() for p in parts if p.strip()]
    if not sents:
        sents = [text.strip()] if text.strip() else []
    return sents

def wrap_words(words, max_words, max_lines):
    if not words:
        return []
    lines = []
    buf = []
    for w in words:
        buf.append(w)
        if len(buf) >= max_words:
            lines.append(" ".join(buf))
            buf = []
            if len(lines) >= max_lines:
                # tout le reste sur la dernière ligne
                buf.extend(words[words.index(w)+1:])
                break
    if buf:
        lines.append(" ".join(buf))
    # Tronquer si on dépasse max_lines
    return lines[:max_lines] if len(lines) > max_lines else lines

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--out", default="subs/captions.ass")

    # Style
    ap.add_argument("--font", default="Arial")
    ap.add_argument("--size", type=int, default=60)
    ap.add_argument("--colour", default="&H00FFFF00")          # Jaune
    ap.add_argument("--outline-colour", default="&H00000000")  # Noir
    ap.add_argument("--back-colour", default="&H64000000")     # Noir semi-trans
    ap.add_argument("--outline", type=float, default=3.0)
    ap.add_argument("--shadow", type=float, default=2.0)
    ap.add_argument("--align", type=int, default=5)            # 5 = centre
    ap.add_argument("--marginv", type=int, default=200)

    # Découpage/tempo
    ap.add_argument("--max-words", type=int, default=4)        # mots par ligne
    ap.add_argument("--max-lines", type=int, default=2)        # lignes par event
    ap.add_argument("--lead", type=float, default=0.0)         # s (apparition plus tôt si >0)
    ap.add_argument("--speed", type=float, default=1.0)        # 1.0 = correspond à audio
    args = ap.parse_args()

    tpath = pathlib.Path(args.transcript)
    apath = pathlib.Path(args.audio)
    opath = pathlib.Path(args.out)
    opath.parent.mkdir(parents=True, exist_ok=True)

    if not tpath.exists() or not tpath.stat().st_size:
        print("Transcript introuvable/vide", file=sys.stderr); sys.exit(1)
    if not apath.exists() or not apath.stat().st_size:
        print("Audio introuvable/vide", file=sys.stderr); sys.exit(1)

    audio_dur = max(0.02, dur_audio(apath))
    raw = tpath.read_text(encoding="utf-8", errors="ignore")
    raw = clean_transcript(raw)

    # Découpe en phrases
    sents = split_sentences(raw)
    if not sents:
        sents = [" "]  # garde-fou

    # Construire lignes par phrase
    sentence_infos = []
    total_words = 0
    for s in sents:
        ws = s.split()
        if not ws:
            continue
        lines = wrap_words(ws, args.max_words, args.max_lines)
        # compter mots réellement utilisés
        used_words = sum(len(l.split()) for l in lines)
        if used_words == 0:
            continue
        sentence_infos.append((used_words, lines))
        total_words += used_words

    if total_words == 0:
        # garde-fou: une ligne pleine durée
        sentence_infos = [(1, [raw.strip() or " "])]
        total_words = 1

    # Durée totale réellement affichée (anti-dérive via speed)
    available = max(0.02, audio_dur - 0.01)
    total_time = min(available, available / max(0.1, args.speed))

    # Répartition proportionnelle
    events = []
    t = 0.0
    for wcount, lines in sentence_infos:
        frac = wcount / total_words
        dur = max(0.25, frac * total_time)  # min 0.25s par event
        s = t
        e = min(available, t + dur)
        # Appliquer lead: avancer l’apparition
        s_shift = max(0.0, s - args.lead)
        e_shift = max(s_shift + 0.01, e - args.lead)
        # Ajouter les lignes (jointes par '\N' pour forcer le retour à la ligne en ASS)
        text = r"\N".join(lines)
        events.append((s_shift, e_shift, text))
        t = e

    # S'assurer que la dernière fin ne dépasse pas la durée audio
    if events:
        s_last, e_last, txt_last = events[-1]
        e_last = min(audio_dur, e_last)
        if e_last <= s_last:
            e_last = min(audio_dur, s_last + 0.25)
        events[-1] = (s_last, e_last, txt_last)

    # Header ASS
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
        "0,0,0,0,100,100,0,0,1,"
        f"{args.outline:.2f},{args.shadow:.2f},{args.align},40,40,{args.marginv},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    with opath.open("w", encoding="utf-8") as f:
        f.write(hdr)
        for s,e,txt in events:
            # IMPORTANT : pas de backslash parasite à la fin
            text = txt.replace("\r", "").strip()
            # Ecrire l’évènement
            f.write(f"Dialogue: 0,{to_ass_ts(s)},{to_ass_ts(e)},TikTok,,0,0,0,,{text}\n")

    print(f"[build_ass] écrit: {opath} (durée audio détectée: {audio_dur:.2f}s)")

if __name__ == "__main__":
    main()
