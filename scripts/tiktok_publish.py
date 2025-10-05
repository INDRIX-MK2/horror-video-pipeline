#!/usr/bin/env python3
import os, sys, json, pathlib, time, re
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent

# ---------- Entrées ----------
DEF_VIDEO   = ROOT / "final_video" / os.environ.get("OUT_NAME", "final_horror.mp4")
TITLE_TXT   = ROOT / "story" / "title.txt"
STORY_TXT   = ROOT / "story" / "story.txt"
CTA_TXT     = ROOT / "story" / "cta.txt"
CAPTION_OUT = ROOT / "final_video" / "caption.txt"
RESP_OUT    = ROOT / "final_video" / "tiktok_response.json"

# ---------- Secrets/Env ----------
OPENAI_API_KEY        = os.environ.get("OPENAI_API_KEY","").strip()

# TikTok : on privilégie l’access token direct ; si refresh présent + client, on tente un refresh
TIKTOK_ACCESS_TOKEN   = os.environ.get("TIKTOK_ACCESS_TOKEN","").strip()
TIKTOK_REFRESH_TOKEN  = os.environ.get("TIKTOK_REFRESH_TOKEN","").strip()
TIKTOK_CLIENT_KEY     = os.environ.get("TIKTOK_CLIENT_KEY","").strip()
TIKTOK_CLIENT_SECRET  = os.environ.get("TIKTOK_CLIENT_SECRET","").strip()

# Endpoints officiels (Open API v2 – à jour au moment de l’écriture ; ajuste si besoin)
TT_REFRESH_URL  = "https://open.tiktokapis.com/v2/oauth/token/"
TT_UPLOAD_URL   = "https://open.tiktokapis.com/v2/video/upload/"
TT_PUBLISH_URL  = "https://open.tiktokapis.com/v2/video/publish/"

# ---------- Utilitaires ----------
def read_text_safe(p: pathlib.Path) -> str:
    if p.exists() and p.stat().st_size:
        return p.read_text(encoding="utf-8", errors="ignore").strip()
    return ""

def sanitize_hashtags(tags):
    out = []
    for t in tags:
        t = t.strip()
        if not t:
            continue
        t = t.lower()
        t = re.sub(r"[^a-z0-9_àâäéèêëîïôöùûüç#]", "", t)
        if not t.startswith("#"):
            t = "#" + t
        if len(t) > 40:   # garde des hashtags courts
            continue
        if t in out:
            continue
        out.append(t)
    return out[:5]

def clip(s, n):
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else (s[:n-1] + "…")

def openai_caption(title:str, story:str) -> dict:
    """
    Retourne un dict: {"caption": "...", "hashtags": ["#..", "#..", ..."]}
    Contrainte : caption <= ~150 chars, 3-5 hashtags max, FR, sans #fyp/#pourtoi.
    """
    if not OPENAI_API_KEY:
        # Fallback sobre si pas d’API
        cap = clip(title or story, 140)
        tags = ["#horreur","#manoir","#pluie"]
        return {"caption": cap, "hashtags": tags}

    url = "https://api.openai.com/v1/chat/completions"
    hdr = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    sys_prompt = (
        "Tu es un social media manager TikTok francophone (thème horreur). "
        "Génère une légende courte (<=150 caractères) et 3-5 hashtags spécifiques. "
        "Évite #fyp, #pourtoi, #viral. Réponds STRICTEMENT en JSON avec "
        "les clés 'caption' (string) et 'hashtags' (array)."
    )
    user = f"TITRE:\n{title}\n\nHISTOIRE:\n{story}\n"
    payload = {
        "model": "gpt-4o",
        "temperature": 1.0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role":"system","content": sys_prompt},
            {"role":"user","content": user}
        ]
    }
    try:
        r = requests.post(url, headers=hdr, json=payload, timeout=60)
        if r.status_code != 200:
            cap = clip(title or story, 140)
            return {"caption": cap, "hashtags": ["#horreur","#suspense"]}
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        obj = json.loads(content)
        cap = clip(str(obj.get("caption","")).strip(), 150)
        tags = sanitize_hashtags(obj.get("hashtags") or [])
        if not tags:
            tags = ["#horreur","#suspense"]
        return {"caption": cap, "hashtags": tags}
    except Exception:
        cap = clip(title or story, 140)
        return {"caption": cap, "hashtags": ["#horreur","#nocturne"]}

def tiktok_refresh_access_token():
    if not (TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET and TIKTOK_REFRESH_TOKEN):
        return ""
    try:
        r = requests.post(
            TT_REFRESH_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": TIKTOK_REFRESH_TOKEN,
                "client_key": TIKTOK_CLIENT_KEY,
                "client_secret": TIKTOK_CLIENT_SECRET,
            },
            timeout=30,
        )
        if r.status_code != 200:
            print(f"[tiktok] refresh token http={r.status_code} body={r.text[:300]}", file=sys.stderr)
            return ""
        return (r.json().get("access_token") or "").strip()
    except Exception as e:
        print(f"[tiktok] refresh exception: {e}", file=sys.stderr)
        return ""

def tiktok_upload(token: str, video_path: pathlib.Path) -> str:
    """
    Upload direct (multipart). Retourne video_id (string) si ok, sinon "".
    """
    try:
        with open(video_path, "rb") as f:
            r = requests.post(
                TT_UPLOAD_URL,
                headers={"Authorization": f"Bearer {token}"},
                files={"video": (video_path.name, f, "video/mp4")},
                timeout=600,
            )
        if r.status_code != 200:
            print(f"[tiktok] upload http={r.status_code} body={r.text[:300]}", file=sys.stderr)
            return ""
        j = r.json()
        # Attendu: {"data":{"video_id":"..."}}
        data = j.get("data") or {}
        vid = (data.get("video_id") or "").strip()
        return vid
    except Exception as e:
        print(f"[tiktok] upload exception: {e}", file=sys.stderr)
        return ""

def tiktok_publish(token: str, video_id: str, caption_text: str) -> dict:
    """
    Publie la vidéo déjà uploadée.
    """
    try:
        payload = {"video_id": video_id, "text": caption_text}
        r = requests.post(
            TT_PUBLISH_URL,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        return {"status_code": r.status_code, "body": r.text}
    except Exception as e:
        return {"status_code": 0, "body": f"exception: {e}"}

def main():
    # ---------- Fichiers obligatoires ----------
    video_path = DEF_VIDEO
    if not video_path.exists() or video_path.stat().st_size == 0:
        print(f"[tiktok_publish] vidéo absente: {video_path}", file=sys.stderr)
        sys.exit(0)  # n'échoue pas le job, on laisse passer

    title = read_text_safe(TITLE_TXT)
    story = read_text_safe(STORY_TXT)
    cta   = read_text_safe(CTA_TXT)

    # ---------- Légende + hashtags via OpenAI ----------
    cap_obj = openai_caption(title, story)
    caption = cap_obj["caption"]
    hashtags = cap_obj["hashtags"]
    full_caption = caption
    if hashtags:
        full_caption = f"{caption}\n{' '.join(hashtags)}"

    CAPTION_OUT.parent.mkdir(parents=True, exist_ok=True)
    CAPTION_OUT.write_text(full_caption + "\n", encoding="utf-8")

    # ---------- Token TikTok (access direct ou refresh) ----------
    token = (TIKTOK_ACCESS_TOKEN or "").strip()
    if not token:
        token = tiktok_refresh_access_token()

    if not token:
        print("[tiktok_publish] Pas de token TikTok. Publication ignorée (la vidéo finale est quand même produite).")
        # On laisse un JSON d’info pour le debug
        RESP_OUT.parent.mkdir(parents=True, exist_ok=True)
        RESP_OUT.write_text(json.dumps({"skipped":"no_token","caption":full_caption}, ensure_ascii=False, indent=2), encoding="utf-8")
        sys.exit(0)

    # ---------- Upload ----------
    vid = tiktok_upload(token, video_path)
    if not vid:
        print("[tiktok_publish] Upload échoué. Voir logs ci-dessus.", file=sys.stderr)
        RESP_OUT.parent.mkdir(parents=True, exist_ok=True)
        RESP_OUT.write_text(json.dumps({"error":"upload_failed"}, ensure_ascii=False, indent=2), encoding="utf-8")
        sys.exit(0)

    # ---------- Publish ----------
    pub = tiktok_publish(token, vid, full_caption)
    RESP_OUT.parent.mkdir(parents=True, exist_ok=True)
    RESP_OUT.write_text(json.dumps({"video_id":vid, "publish":pub, "caption":full_caption}, ensure_ascii=False, indent=2), encoding="utf-8")

    if 200 <= pub.get("status_code", 0) < 300:
        print(f"[tiktok_publish] Publication OK (video_id={vid}).")
    else:
        print(f"[tiktok_publish] Publication potentiellement échouée http={pub.get('status_code')} body={pub.get('body','')[:300]}", file=sys.stderr)
        # on n’échoue pas le job : sys.exit(0)

if __name__ == "__main__":
    main()