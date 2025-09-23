#!/usr/bin/env python3
import os, json, pathlib, sys, urllib.request

# --- Config ENV
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
SYSTEM_PROMPT  = os.environ.get("SYSTEM_PROMPT", "Tu écris un script court et immersif d'horreur en français. N'inclus AUCUNE didascalie (intro, scène, narrateur, CTA, etc.). Raconte seulement l'histoire.")
USER_PROMPT    = os.environ.get("USER_PROMPT", "Écris un script TikTok de 180 à 200 mots (65-75s). Thème : horreur atmosphérique, manoir, pluie, bruits métalliques. Style concis, phrases courtes, sans grossièretés.")

if not OPENAI_API_KEY:
    print("OPENAI_API_KEY manquant", file=sys.stderr)
    sys.exit(1)

out_dir = pathlib.Path("story")
out_dir.mkdir(parents=True, exist_ok=True)
out_file = out_dir/"story.txt"

# --- Requête OpenAI (Chat Completions)
payload = {
    "model": "gpt-4o-mini",
    "temperature": 0.9,
    "messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_PROMPT}
    ]
}
data = json.dumps(payload).encode("utf-8")

req = urllib.request.Request(
    "https://api.openai.com/v1/chat/completions",
    data=data,
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}",
    },
    method="POST",
)

try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        txt = (res["choices"][0]["message"]["content"] or "").strip()
except Exception as e:
    print(f"Erreur OpenAI: {e}", file=sys.stderr)
    sys.exit(1)

# Nettoyage minimal : enlever guillemets globaux et marqueurs indésirables
txt = txt.replace("\r", "")
lines = [l.strip() for l in txt.split("\n") if l.strip()]
txt = " ".join(lines)
# Supprime mots clefs fréquents de didascalies s'ils apparaissent en tête
banheads = ("scène", "scene", "intro", "hook", "narrateur", "cta")
if txt.lower().split(":")[0] in banheads:
    txt = ":".join(txt.split(":")[1:]).strip()

if not txt:
    print("Texte vide généré.", file=sys.stderr)
    sys.exit(1)

out_file.write_text(txt, encoding="utf-8")
print(f"OK: {out_file} ({len(txt.split())} mots)")