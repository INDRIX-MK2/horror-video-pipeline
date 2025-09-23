#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Génère subtitles/captions.ass (karaoké) synchronisé sur audio/voice.wav.

- Lit l’histoire (story/story.txt). Si story/story_clean.txt existe, on le préfère.
- Retire automatiquement les didascalies (intro, scène, narrateur, CTA, etc.).
- Mesure la durée de la voix via ffprobe (pas de heredoc).
- Répartit la durée MOT PAR MOT (tag {\kNN} en centisecondes).
- Groupage en lignes lisibles (~4–8 mots, >=1.2s/ligne).
- Écrit un .ass avec Style "TikTok" (défini dans ass_header.ass).

Prérequis: ffmpeg/ffprobe installés. Fichiers attendus:
- subtitles/ass_header.ass (fourni)
- audio/voice.wav (généré par voice_elevenlabs.py)
"""

import re
import math
import shlex
import subprocess
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parents[1]
STORY_RAW = ROOT / "story" / "story.txt"
STORY_CLEAN = ROOT / "story" / "story_clean.txt"
AUDIO_FILE = ROOT / "audio" / "voice.wav"
ASS_HEADER = ROOT / "subtitles" / "ass_header.ass"
ASS_OUT = ROOT / "subtitles" / "captions.ass"

# ------------------------ Utils ------------------------

def run_ffprobe_duration(path: Path) -> float:
    """Retourne la durée (en secondes, float) du flux audio a:0 via ffprobe."""
    if not path.is_file():
        raise FileNotFoundError(f"Audio introuvable: {path}")
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path)
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    s = proc.stdout.strip()
    try:
        return float(s)
    except Exception as e:
        raise RuntimeError(f"Impossible de lire la durée via ffprobe (stdout='{s}'): {e}")

def tcode(seconds: float) -> str:
    """Format ASS h:MM:SS.cc (centisecondes)."""
    if seconds < 0:
        seconds = 0.0
    cs = int(round(seconds * 100.0))
    h = cs // (100*3600)
    rem = cs % (100*3600)
    m = rem // (100*60)
    rem = rem % (100*60)
    s = rem // 100
    c = rem % 100
    return f"{h:d}:{m:02d}:{s:02d}.{c:02d}"

def normalize_text(txt: str) -> str:
    """Nettoie: supprime didascalies et ponctuation parasite, condense espaces."""
    # Supprimer guillemets isolés
    txt = txt.replace("“", "\"").replace("”", "\"")
    txt = txt.replace("’", "'").replace("«", "\"").replace("»", "\"")

    # Retirer didascalies (intro, scène, narrateur, cta, etc.)
    # Variantes communes + erreurs OCR (p.ex. 'Seine' au lieu de 'Scène')
    didascalies = [
        r"intro", r"hook", r"accroche",
        r"sc[èe]ne", r"scene", r"seine",
        r"narrateur", r"voix(?:\s*off)?",
        r"cta", r"appel\s*(?:à|a)\s*l(?:’|')?action",
        r"d[ée]veloppement", r"developpement",
        r"conclusion", r"fin", r"gros\s*plan", r"plan\s*(?:large|rapproch[ée]?)",
    ]
    pat = r"(?i)\b(?:" + "|".join(didascalies) + r")\b[:;,.\-–—]*"
    txt = re.sub(pat, " ", txt)

    # Retirer blocs entre parenthèses/crochets/accolades (indications de scène)
    txt = re.sub(r"[\(\[\{][^\)\]\}]*[\)\]\}]", " ", txt)

    # Compresser espaces
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt

def tokenize(txt: str) -> List[str]:
    """
    Tokenise en mots + ponctuation (on garde .,;:!?… séparés pour un timing léger).
    """
    tokens = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+'?[A-Za-zÀ-ÖØ-öø-ÿ0-9]+|[A-Za-zÀ-ÖØ-öø-ÿ0-9]+|[.,;:!?…]", txt)
    return tokens

def distribute_centiseconds(total_cs: int, n: int, punct_idx: List[int]) -> List[int]:
    """
    Répartit total_cs sur n tokens. Ponctuation reçoit peu (6cs), mots reçoivent le reste.
    Ajuste la somme pour coller exactement à total_cs.
    """
    if n <= 0 or total_cs <= 0:
        return []

    base_punct = 6  # 0.06 s par ponctuation
    cs = [0]*n
    n_punct = len(punct_idx)
    total_punct = base_punct * n_punct
    total_words = max(0, total_cs - total_punct)
    n_words = n - n_punct
    if n_words <= 0:
        # que ponctuation: tout en ponctuation
        for i in punct_idx:
            cs[i] = base_punct
        # ajustement
        diff = total_cs - sum(cs)
        i = 0
        while diff != 0 and i < n:
            step = 1 if diff > 0 else -1
            cs[i] += step
            diff -= step
            i = (i + 1) % n
        return cs

    per_word = max(8, int(round(total_words / n_words)))  # >= 0.08s par mot
    for i in range(n):
        if i in punct_idx:
            cs[i] = base_punct
        else:
            cs[i] = per_word

    # Ajustement fin pour respecter exactement total_cs
    diff = total_cs - sum(cs)
    i = 0
    while diff != 0 and n > 0:
        if i not in punct_idx:  # ajuste de préférence les mots
            step = 1 if diff > 0 else -1
            # garde une borne basse raisonnable
            if cs[i] + step >= 6:
                cs[i] += step
                diff -= step
        i = (i + 1) % n
    return cs

def group_lines(tokens: List[str], cs: List[int]) -> List[Tuple[List[str], List[int]]]:
    """
    Regroupe en lignes lisibles (~4–8 tokens), et >= 1.2s par ligne si possible.
    """
    lines = []
    buf_toks, buf_cs = [], []
    acc = 0
    # bornes
    min_line_cs = 120  # 1.2s
    max_tokens = 8
    soft_tokens = 6

    for i, (w, k) in enumerate(zip(tokens, cs)):
        buf_toks.append(w)
        buf_cs.append(k)
        acc += k

        end_of_sentence = (w in [".", "!", "?", "…"])
        enough_tokens = (len(buf_toks) >= soft_tokens)
        hard_cap = (len(buf_toks) >= max_tokens)
        enough_time = (acc >= min_line_cs)

        if end_of_sentence and enough_time:
            lines.append((buf_toks, buf_cs))
            buf_toks, buf_cs, acc = [], [], 0
        elif hard_cap and enough_time:
            lines.append((buf_toks, buf_cs))
            buf_toks, buf_cs, acc = [], [], 0

    if buf_toks:
        lines.append((buf_toks, buf_cs))
    return lines

def build_kara_text(words: List[str], cs: List[int]) -> str:
    """
    Construit le texte karaoké: {\kNN}mot ...
    Attention: pour écrire des accolades dans f-string => double accolades.
    """
    parts = []
    for w, k in zip(words, cs):
        parts.append(f"{{\\k{k}}}{w} ")
    return "".join(parts).rstrip()

# ------------------------ Main ------------------------

def main():
    # 1) Lire l’histoire
    src = STORY_CLEAN if STORY_CLEAN.is_file() else STORY_RAW
    if not src.is_file():
        raise FileNotFoundError(f"Histoire introuvable: {src}")
    text = src.read_text(encoding="utf-8").strip()

    # 2) Nettoyage (anti-didascalies)
    text = normalize_text(text)

    # Sécurité : si vide, on évite de générer un .ass vide
    if not text:
        raise RuntimeError("Le texte nettoyé est vide après suppression des didascalies.")

    # 3) Durée audio
    duration = run_ffprobe_duration(AUDIO_FILE)  # secondes float
    total_cs = max(1, int(round(duration * 100.0)))

    # 4) Tokenisation + attribution des centisecondes
    tokens = tokenize(text)
    if not tokens:
        raise RuntimeError("Aucun token après tokenisation.")

    punct_idx = [i for i, t in enumerate(tokens) if t in [".", ",", ";", ":", "!", "?", "…"]]
    cs = distribute_centiseconds(total_cs, len(tokens), punct_idx)

    # 5) Groupage en lignes
    grouped = group_lines(tokens, cs)

    # 6) Écriture du .ass
    ASS_OUT.parent.mkdir(parents=True, exist_ok=True)
    if not ASS_HEADER.is_file():
        raise FileNotFoundError(f"Header ASS manquant: {ASS_HEADER}")

    header = ASS_HEADER.read_text(encoding="utf-8")
    with ASS_OUT.open("w", encoding="utf-8", newline="\n") as f:
        f.write(header.rstrip("\n") + "\n")
        t = 0  # en centisecondes
        for words, klist in grouped:
            dur_line = sum(klist)
            start = t / 100.0
            end = (t + dur_line) / 100.0
            kara = build_kara_text(words, klist)
            f.write(f"Dialogue: 0,{tcode(start)},{tcode(end)},TikTok,,0,0,0,,{kara}\n")
            t += dur_line

        # Ajuste la dernière ligne si sous/over vs. durée voix (petit delta)
        final_end = t / 100.0
        delta = duration - final_end
        if abs(delta) >= 0.02:
            # Ajouter une micro-pause en fin OU rogner la dernière ligne légèrement
            # (option sûre: on laisse tel quel, le renderer -shortest coupera proprement).
            pass

    print(f"[OK] Sous-titres écrits : {ASS_OUT} (durée voix ~ {duration:.2f}s)")

if __name__ == "__main__":
    main()
