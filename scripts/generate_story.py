#!/usr/bin/env python3
import os, json, sys, pathlib, urllib.request, re

OUT_DIR = pathlib.Path("story")
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_FILE = OUT_DIR / "story.txt"

API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
if not API_KEY:
    print("OPENAI_API_KEY manquant", file=sys.stderr); sys.exit(1)

SYSTEM_PROMPT = os.environ.get("SYSTEM_PROMPT", "").strip()
USER_PROMPT   = os.environ.get("USER_PROMPT", "").strip()
if not USER_PROMPT:
    print("USER_PROMPT manquant", file=sys.stderr); sys.exit(1)

payload = {
    "model": "gpt-4o-mini",
    "temperature": 1,
    "messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_PROMPT}
    ]
}
req = urllib.request.Request(
    "https://api.openai.com/v1/chat/completions",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
    method="POST"
)

try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
except Exception as e:
    print(f"Erreur OpenAI: {e}", file=sys.stderr); sys.exit(1)

text = (text or "").strip()
if not text:
    print("Réponse vide du modèle", file=sys.stderr); sys.exit(1)

# Nettoyage: supprime didascalies et mentions de voix
lines = []
for raw in text.splitlines():
    s = raw.strip()
    # retire balises entre [] ou ()
    s = re.sub(r"\[[^\]]+\]", "", s)
    s = re.sub(r"\([^)]+\)", "", s)
    # retire préfixes de didascalies
    for pref in ("intro", "hook", "scène", "scene", "narrateur", "cta", "voix 1", "voix 2", "voice 1", "voice 2"):
        if s.lower().startswith(pref + ":"):
            s = s.split(":",1)[1].strip()
    if s:
        lines.append(s)

OUT_FILE.write_text("\n".join(lines), encoding="utf-8")
print(f"[generate_story] story écrit: {OUT_FILE} ({len(lines)} lignes)")