#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generate title + story + CTA with OpenAI, and always write:
- story/title.txt
- story/story.txt
- story/cta.txt

Hard requirements:
- No stage directions / no "SCÈNE", "NARRATEUR", etc. in story.
- Title: short, punchy, summarizes the story.
- CTA: 1–2 short lines (subscribe/share).
"""

import os, sys, json, pathlib, textwrap, re
import requests

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY".lower())
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")  # tu as demandé gpt-4o
TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "1"))

OUT_DIR = pathlib.Path("story")
TITLE_FILE = OUT_DIR / "title.txt"
STORY_FILE = OUT_DIR / "story.txt"
CTA_FILE = OUT_DIR / "cta.txt"

# Prompts
SYSTEM_PROMPT = (
    "Tu es un auteur de micro-histoires d'horreur en français. "
    "Tu écris de façon immersive, sans didascalies, sans mentions de scène, sans 'Narrateur'. "
    "Phrases courtes. Atmosphérique. Zéro grossièreté."
)

# Le user prompt cible 180–200 mots et exige un TITRE distinct + CTA distinct.
USER_PROMPT = (
    "Écris une histoire d'horreur atmosphérique (manoir, pluie, bruits métalliques), "
    "en 180 à 200 mots, phrases courtes, sans didascalies (pas d'« intro », « scène », « narrateur »). "
    "Donne aussi: (1) un TITRE bref qui résume l'histoire (6–10 mots max), "
    "(2) un CTA de 1 à 2 lignes invitant à s'abonner et partager. "
    "Réponds STRICTEMENT en JSON UTF-8 avec les clés: "
    '{"title": "...", "story": "...", "cta": "..."}'
)

DEFAULT_CTA = "Abonne-toi pour d'autres frissons.\nPartage si tu as osé regarder jusqu'au bout."

def _clean_text(s: str) -> str:
    """Supprime crochets/parenthèses et espaces multiples."""
    s = s.replace("\r", "")
    s = re.sub(r"\[[^\]]*\]", "", s)
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def call_openai(system_prompt: str, user_prompt: str) -> dict:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "temperature": TEMPERATURE,
        "messages": [
            {"role":"system", "content": system_prompt},
            {"role":"user",   "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=90)
    r.raise_for_status()
    data = r.json()
    raw = data["choices"][0]["message"]["content"]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # certains modèles peuvent entourer de texte – tenter une extraction JSON
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            return json.loads(m.group(0))
        raise

def ensure_text_files(title: str, story: str, cta: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TITLE_FILE.write_text(title.strip() + "\n", encoding="utf-8")
    STORY_FILE.write_text(story.strip() + "\n", encoding="utf-8")
    # CTA toujours présent
    cta_final = (cta or "").strip() or DEFAULT_CTA
    CTA_FILE.write_text(cta_final + "\n", encoding="utf-8")

def main():
    if not OPENAI_API_KEY:
        print("OPENAI_API_KEY manquant", file=sys.stderr)
        sys.exit(1)

    try:
        j = call_openai(SYSTEM_PROMPT, USER_PROMPT)
    except Exception as e:
        # fallback ultra-robuste : on fabrique au moins des fichiers pour ne pas bloquer la pipeline
        print(f"[generate_story] Avertissement: API failure -> {e}", file=sys.stderr)
        title = "La Chaîne Dans Le Noir"
        story = (
            "La pluie bat le toit. Le manoir respire. Un couloir luisant, des portraits sans pupilles. "
            "Au loin, une chaîne traîne, racle la pierre. Un pas derrière moi. Je me fige. "
            "Le métal résonne, approche, pulse comme un cœur. Une porte s’entrouvre, soupire. "
            "L’odeur de moisissure brûle la gorge. Je n’ose pas tourner la tête. "
            "La chaîne s’enroule autour de ma cheville. Tiraillement. Je vacille. "
            "Dans la vitre, un reflet sans visage. Les murs se penchent, écoutent. "
            "Un dernier éclair blanchit l’escalier. Quelque chose descend. Lentement. "
            "Je retiens mon souffle. Dans le noir, la chaîne sourit."
        )
        ensure_text_files(_clean_text(title), _clean_text(story), DEFAULT_CTA)
        print("[generate_story] titre -> story/title.txt | histoire -> story/story.txt | cta -> story/cta.txt")
        return

    # Normal path
    title = _clean_text(j.get("title", ""))
    story = _clean_text(j.get("story", ""))
    cta   = _clean_text(j.get("cta", ""))

    # Sécurités supplémentaires
    if not title:
        # fabriquer un titre court depuis la 1re phrase de l’histoire
        head = story.split(".")[0]
        words = head.split()
        title = " ".join(words[:10]) if words else "Nuit de Chaînes"

    # Interdiction de didascalies dans l'histoire
    banned = re.compile(r"\b(intro|scène|narrateur|hook|cta)\b", re.I)
    story = banned.sub("", story)
    story = re.sub(r"\s{2,}", " ", story).strip()

    ensure_text_files(title, story, cta)
    print("[generate_story] titre -> story/title.txt | histoire -> story/story.txt | cta -> story/cta.txt")

if __name__ == "__main__":
    main()