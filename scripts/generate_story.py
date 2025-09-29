#!/usr/bin/env python3
import os, json, sys, pathlib, re, urllib.request

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")   # tu as demandé gpt-4o
TEMPERATURE = float(os.environ.get("OPENAI_TEMPERATURE", "1"))

SYSTEM_PROMPT = os.environ.get("SYSTEM_PROMPT", "Tu écris un script court et immersif d'horreur en français. N'inclus AUCUNE didascalie (intro, scène, narrateur, CTA, etc.). Raconte seulement l'histoire.")
USER_PROMPT = os.environ.get("USER_PROMPT", "Écris un script TikTok immerssif de 180 à 200 mots (65-75s). Structure : hook (10s), développement (45s), conclusion avec CTA (10s). Thème : horreur atmosphérique. Style concis, phrases courtes, sans grossièretés.")

API_KEY = os.environ.get("OPENAI_API_KEY")
if not API_KEY:
    print("OPENAI_API_KEY manquant", file=sys.stderr)
    sys.exit(1)

out_dir = pathlib.Path("story")
out_dir.mkdir(parents=True, exist_ok=True)
story_path = out_dir / "story.txt"
title_path = out_dir / "title.txt"

# Demande stricte: JSON avec { "title": "...", "story": "..." }
sys_msg = (
    SYSTEM_PROMPT
    + "\n\nFormat de réponse STRICT: renvoie UNIQUEMENT du JSON avec les clés EXACTES:\n"
      '{ "title": "<titre court et percutant qui résume l\'histoire, 3–8 mots, max ~60 caractères>", '
      '"story": "<histoire complète sans didascalies>"}\n'
      "Pas de texte en dehors du JSON."
)

payload = {
    "model": MODEL,
    "temperature": TEMPERATURE,
    "response_format": {"type": "json_object"},
    "messages": [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": USER_PROMPT}
    ],
}

req = urllib.request.Request(
    "https://api.openai.com/v1/chat/completions",
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    },
    method="POST",
)

def clean_text(s: str) -> str:
    # supprime didascalies éventuelles résiduelles
    s = re.sub(r"\[[^\]]+\]", " ", s)
    s = re.sub(r"\([^)]+\)", " ", s)
    s = re.sub(r"\b(?:intro|scène|scene|narrateur|voix ?\d+|cta)\b[:\-\]]*", " ", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s

try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = data["choices"][0]["message"]["content"]
    obj = json.loads(content)
    title = clean_text(obj.get("title", "").strip())
    story = obj.get("story", "").strip()

    story = clean_text(story)

    # garde un titre sûr
    if not title:
        # fallback simple si le JSON n’a pas de titre
        first_line = story.split("\n", 1)[0]
        title = " ".join(first_line.split()[:8])
    # borne dure sur la longueur
    if len(title) > 64:
        title = title[:64].rstrip(" ,;:.!?…") + "…"

    title_path.write_text(title, encoding="utf-8")
    story_path.write_text(story, encoding="utf-8")
    print(f"[generate_story] titre -> {title_path} | histoire -> {story_path}")

except Exception as e:
    print(f"[generate_story] ERREUR API ou parsing: {e}", file=sys.stderr)
    # Fallback minimal : on écrit au moins une histoire basique
    fallback = "La maison respire. La pluie frappe. Quelque chose m'observe."
    story_path.write_text(fallback, encoding="utf-8")
    title_path.write_text("La Maison Qui Respire", encoding="utf-8")
    sys.exit(0)
