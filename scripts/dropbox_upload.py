#!/usr/bin/env python3
import argparse, os, sys, json, time, pathlib, requests

# Ce script n'accepte PAS d'access token direct.
# Il échange DROPBOX_REFRESH_TOKEN -> access_token à chaque run.
# Puis upload (<=150MB direct, sinon chunké) et crée un lien partageable.

TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
UPLOAD_URL = "https://content.dropboxapi.com/2/files/upload"
UPLOAD_START = "https://content.dropboxapi.com/2/files/upload_session/start"
UPLOAD_APPEND = "https://content.dropboxapi.com/2/files/upload_session/append_v2"
UPLOAD_FINISH = "https://content.dropboxapi.com/2/files/upload_session/finish"
LINK_CREATE = "https://api.dropboxapi.com/2/sharing/create_shared_link_with_settings"
LINK_LIST   = "https://api.dropboxapi.com/2/sharing/list_shared_links"

def get_access_token(app_key, app_secret, refresh_token):
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    resp = requests.post(TOKEN_URL, data=data, auth=(app_key, app_secret), timeout=30)
    if resp.status_code != 200:
        print(f"[dropbox] token http={resp.status_code} body={resp.text}", file=sys.stderr)
        sys.exit(1)
    j = resp.json()
    return j.get("access_token")

def upload_small(access_token, file_path, remote_path):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Dropbox-API-Arg": json.dumps({
            "path": remote_path, "mode":"add", "autorename": True, "mute": False
        }),
        "Content-Type": "application/octet-stream"
    }
    with open(file_path, "rb") as f:
        resp = requests.post(UPLOAD_URL, headers=headers, data=f, timeout=600)
    if resp.status_code not in range(200,300):
        print(f"[dropbox] upload error http={resp.status_code} body={resp.text}", file=sys.stderr)
        sys.exit(1)

def upload_large(access_token, file_path, remote_path, chunk=15*1024*1024):
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type":"application/octet-stream"}
    # start
    h = headers.copy()
    h["Dropbox-API-Arg"] = json.dumps({"close": False})
    r = requests.post(UPLOAD_START, headers=h, data=b"", timeout=60)
    if r.status_code not in range(200,300):
        print(f"[dropbox] start error http={r.status_code} body={r.text}", file=sys.stderr)
        sys.exit(1)
    sid = r.json()["session_id"]
    # append
    size = os.path.getsize(file_path)
    off = 0
    with open(file_path, "rb") as f:
        while off < size:
            data = f.read(chunk)
            h = headers.copy()
            h["Dropbox-API-Arg"] = json.dumps({
                "cursor": {"session_id": sid, "offset": off},
                "close": False
            })
            rr = requests.post(UPLOAD_APPEND, headers=h, data=data, timeout=600)
            if rr.status_code not in range(200,300):
                print(f"[dropbox] append error http={rr.status_code} body={rr.text}", file=sys.stderr)
                sys.exit(1)
            off += len(data)
    # finish
    h = headers.copy()
    h["Dropbox-API-Arg"] = json.dumps({
        "cursor": {"session_id": sid, "offset": size},
        "commit": {"path": remote_path, "mode":"add", "autorename": True, "mute": False}
    })
    rf = requests.post(UPLOAD_FINISH, headers=h, data=b"", timeout=120)
    if rf.status_code not in range(200,300):
        print(f"[dropbox] finish error http={rf.status_code} body={rf.text}", file=sys.stderr)
        sys.exit(1)

def create_or_get_link(access_token, remote_path):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type":"application/json"
    }
    # try create
    r = requests.post(LINK_CREATE, headers=headers, data=json.dumps({"path": remote_path}), timeout=30)
    if r.status_code in range(200,300):
        url = r.json().get("url","")
        return url.replace("?dl=0","?dl=1") if url else ""
    # else list
    r2 = requests.post(LINK_LIST, headers=headers, data=json.dumps({"path": remote_path,"direct_only":True}), timeout=30)
    if r2.status_code in range(200,300):
        links = r2.json().get("links") or []
        if links:
            url = links[0].get("url","")
            return url.replace("?dl=0","?dl=1") if url else ""
    print(f"[dropbox] cannot obtain shared link (http={r.status_code}/{r2.status_code})", file=sys.stderr)
    return ""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--remote-dir", default="/horror")
    ap.add_argument("--out-link", default="final_video/dropbox_link.txt")
    args = ap.parse_args()

    app_key = os.environ.get("DROPBOX_APP_KEY","").strip()
    app_sec = os.environ.get("DROPBOX_APP_SECRET","").strip()
    ref_tok = os.environ.get("DROPBOX_REFRESH_TOKEN","").strip()

    if not app_key or not app_sec or not ref_tok:
        print("DROPBOX_APP_KEY / DROPBOX_APP_SECRET / DROPBOX_REFRESH_TOKEN manquants", file=sys.stderr)
        sys.exit(1)

    p = pathlib.Path(args.file)
    if not p.exists() or p.stat().st_size == 0:
        print(f"Fichier manquant/vide: {p}", file=sys.stderr); sys.exit(1)

    ts = time.strftime("%Y%m%d_%H%M%S")
    remote_path = f"{args.remote-dir.rstrip('/')}/{ts}_{p.name}"
    # corrigé: dash dans remote-dir → remplacer par underscore pour clé python
    remote_dir = args.remote_dir.rstrip("/")
    remote_path = f"{remote_dir}/{ts}_{p.name}"

    access_token = get_access_token(app_key, app_sec, ref_tok)

    size = p.stat().st_size
    if size <= 150*1024*1024:
        upload_small(access_token, str(p), remote_path)
    else:
        upload_large(access_token, str(p), remote_path)

    url = create_or_get_link(access_token, remote_path)
    if not url:
        print("Impossible d'obtenir le lien de partage Dropbox", file=sys.stderr)
        sys.exit(1)

    out = pathlib.Path(args.out_link)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(url, encoding="utf-8")
    print(f"[dropbox] OK: {url}")

if __name__ == "__main__":
    main()
