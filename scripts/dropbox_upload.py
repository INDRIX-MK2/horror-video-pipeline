#!/usr/bin/env python3
import os, sys, json, pathlib, time, subprocess
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_NAME = os.environ.get("OUT_NAME","final_horror.mp4")
FILE = ROOT / "final_video" / OUT_NAME
LINK_TXT = ROOT / "final_video" / "dropbox_link.txt"
LINK_TXT.parent.mkdir(parents=True, exist_ok=True)

if not FILE.exists() or FILE.stat().st_size == 0:
    print(f"Fichier absent ou vide: {FILE}", file=sys.stderr); sys.exit(1)

# Auth: priorité au flux Refresh Token
ACCESS_TOKEN = os.environ.get("DROPBOX_ACCESS_TOKEN","").strip()
APP_KEY = os.environ.get("DROPBOX_APP_KEY","").strip()
APP_SECRET = os.environ.get("DROPBOX_APP_SECRET","").strip()
REFRESH_TOKEN = os.environ.get("DROPBOX_REFRESH_TOKEN","").strip()

def get_access_token_from_refresh():
    if not (APP_KEY and APP_SECRET and REFRESH_TOKEN):
        return ""
    url = "https://api.dropboxapi.com/oauth2/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": APP_KEY,
        "client_secret": APP_SECRET
    }
    r = requests.post(url, data=data, timeout=30)
    if r.status_code != 200:
        print(f"Dropbox token refresh HTTP {r.status_code}: {r.text[:300]}", file=sys.stderr)
        return ""
    return r.json().get("access_token","")

def upload_simple(token: str, local: pathlib.Path, remote_path: str) -> bool:
    url = "https://content.dropboxapi.com/2/files/upload"
    headers = {
        "Authorization": f"Bearer {token}",
        "Dropbox-API-Arg": json.dumps({
            "path": remote_path, "mode": "add", "autorename": True, "mute": False
        }),
        "Content-Type": "application/octet-stream"
    }
    with open(local, "rb") as f:
        r = requests.post(url, headers=headers, data=f, timeout=600)
    if r.status_code not in (200, 409):  # 409 possible si conflit (autorename gère)
        print(f"UPLOAD http={r.status_code} body={r.text[:300]}", file=sys.stderr)
        return False
    return True

def upload_chunked(token: str, local: pathlib.Path, remote_path: str, chunk=15*1024*1024) -> bool:
    start_url = "https://content.dropboxapi.com/2/files/upload_session/start"
    append_url = "https://content.dropboxapi.com/2/files/upload_session/append_v2"
    finish_url = "https://content.dropboxapi.com/2/files/upload_session/finish"

    # start
    r = requests.post(start_url,
                      headers={"Authorization": f"Bearer {token}",
                               "Content-Type": "application/octet-stream",
                               "Dropbox-API-Arg": json.dumps({"close": False})},
                      data=b"", timeout=60)
    if r.status_code != 200:
        print(f"SESSION start http={r.status_code} body={r.text[:200]}", file=sys.stderr)
        return False
    sid = r.json()["session_id"]

    size = local.stat().st_size
    off = 0
    with open(local, "rb") as f:
        while off < size:
            chunk_data = f.read(chunk)
            r = requests.post(append_url,
                              headers={"Authorization": f"Bearer {token}",
                                       "Content-Type": "application/octet-stream",
                                       "Dropbox-API-Arg": json.dumps({"cursor":{"session_id":sid,"offset":off},"close": False})},
                              data=chunk_data, timeout=600)
            if r.status_code != 200:
                print(f"SESSION append http={r.status_code} body={r.text[:200]}", file=sys.stderr)
                return False
            off += len(chunk_data)

    commit = {
        "cursor": {"session_id": sid, "offset": size},
        "commit": {"path": remote_path, "mode": "add", "autorename": True, "mute": False}
    }
    r = requests.post(finish_url,
                      headers={"Authorization": f"Bearer {token}",
                               "Content-Type": "application/octet-stream",
                               "Dropbox-API-Arg": json.dumps(commit)},
                      data=b"", timeout=120)
    if r.status_code != 200:
        print(f"SESSION finish http={r.status_code} body={r.text[:300]}", file=sys.stderr)
        return False
    return True

def create_share_link(token: str, remote_path: str) -> str:
    url_create = "https://api.dropboxapi.com/2/sharing/create_shared_link_with_settings"
    r = requests.post(url_create,
                      headers={"Authorization": f"Bearer {token}",
                               "Content-Type": "application/json"},
                      json={"path": remote_path}, timeout=30)
    if r.status_code == 200:
        return r.json().get("url","")
    # sinon on tente list_shared_links
    url_list = "https://api.dropboxapi.com/2/sharing/list_shared_links"
    r2 = requests.post(url_list,
                       headers={"Authorization": f"Bearer {token}",
                                "Content-Type": "application/json"},
                       json={"path": remote_path, "direct_only": True}, timeout=30)
    if r2.status_code == 200:
        links = r2.json().get("links") or []
        if links:
            return links[0].get("url","")
    return ""

# Token effectif
token = ""
if APP_KEY and APP_SECRET and REFRESH_TOKEN:
    token = get_access_token_from_refresh()
elif ACCESS_TOKEN:
    token = ACCESS_TOKEN

if not token:
    print("Pas de token Dropbox disponible, upload ignoré.", file=sys.stderr)
    sys.exit(0)  # on ne bloque pas le job

remote_dir = "/horror"
ts = time.strftime("%Y%m%d_%H%M%S")
remote_path = f"{remote_dir}/{ts}_{FILE.name}"

size = FILE.stat().st_size
ok = False
if size <= 150*1024*1024:
    ok = upload_simple(token, FILE, remote_path)
else:
    ok = upload_chunked(token, FILE, remote_path)

if not ok:
    print("Échec upload Dropbox", file=sys.stderr); sys.exit(1)

link = create_share_link(token, remote_path)
if not link:
    print("Impossible d'obtenir un lien de partage", file=sys.stderr); sys.exit(1)

# dl=1
if link.endswith("?dl=0"):
    link = link[:-5] + "?dl=1"
LINK_TXT.write_text(link + "\n", encoding="utf-8")
print(f"Dropbox direct link: {link}")