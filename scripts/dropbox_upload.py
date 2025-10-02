#!/usr/bin/env python3
# coding: utf-8
import argparse, pathlib, sys, time, json, os, base64
import urllib.request, urllib.error, urllib.parse  # <- parse importé

OAUTH_TOKEN_URL = "https://api.dropbox.com/oauth2/token"
UPLOAD_URL      = "https://content.dropboxapi.com/2/files/upload"
UPLOAD_START    = "https://content.dropboxapi.com/2/files/upload_session/start"
UPLOAD_APPEND   = "https://content.dropboxapi.com/2/files/upload_session/append_v2"
UPLOAD_FINISH   = "https://content.dropboxapi.com/2/files/upload_session/finish"
LINK_CREATE     = "https://api.dropboxapi.com/2/sharing/create_shared_link_with_settings"
LINK_LIST       = "https://api.dropboxapi.com/2/sharing/list_shared_links"

CHUNK_SIZE  = 15 * 1024 * 1024   # 15MB
SMALL_LIMIT = 150 * 1024 * 1024  # 150MB

def http_json(url, data=None, headers=None, method="POST"):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read(), resp.getcode()
    except urllib.error.HTTPError as e:
        body = e.read()
        return body, e.code
    except Exception as e:
        return str(e).encode("utf-8"), 0

def oauth_refresh(app_key, app_secret, refresh_token):
    # Corps x-www-form-urlencoded
    payload = (
        "grant_type=refresh_token&refresh_token="
        + urllib.parse.quote(refresh_token)
    ).encode("utf-8")

    # En-tête Basic correct (Base64 de "app_key:app_secret")
    basic = "Basic " + base64.b64encode(f"{app_key}:{app_secret}".encode("utf-8")).decode("ascii")

    body, code = http_json(
        OAUTH_TOKEN_URL,
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": basic,
        },
        method="POST",
    )
    if code != 200:
        sys.stderr.write(f"[dropbox] Refresh token échec http={code} body={body[:400]!r}\n")
        return None
    try:
        j = json.loads(body.decode("utf-8"))
        return j.get("access_token")
    except Exception:
        return None

def upload_small(access_token, local_path: pathlib.Path, remote_path: str):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Dropbox-API-Arg": json.dumps({
            "path": remote_path,
            "mode": "add",
            "autorename": True,
            "mute": False
        }),
        "Content-Type": "application/octet-stream"
    }
    data = local_path.read_bytes()
    return http_json(UPLOAD_URL, data=data, headers=headers, method="POST")

def upload_large(access_token, local_path: pathlib.Path, remote_path: str):
    # start
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/octet-stream",
        "Dropbox-API-Arg": json.dumps({"close": False})
    }
    body, code = http_json(UPLOAD_START, data=b"", headers=headers, method="POST")
    if code != 200:
        return code, body
    try:
        sid = json.loads(body.decode("utf-8"))["session_id"]
    except Exception:
        return 0, b"invalid start response"

    size = local_path.stat().st_size
    sent = 0
    with local_path.open("rb") as f:
        while sent < size:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/octet-stream",
                "Dropbox-API-Arg": json.dumps({
                    "cursor": {"session_id": sid, "offset": sent},
                    "close": False
                })
            }
            body, code = http_json(UPLOAD_APPEND, data=chunk, headers=headers, method="POST")
            if code != 200:
                return code, body
            sent += len(chunk)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/octet-stream",
        "Dropbox-API-Arg": json.dumps({
            "cursor": {"session_id": sid, "offset": size},
            "commit": {"path": remote_path, "mode": "add", "autorename": True, "mute": False}
        })
    }
    return http_json(UPLOAD_FINISH, data=b"", headers=headers, method="POST")

def ensure_shared_link(access_token, remote_path: str):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    # tenter création
    body, code = http_json(
        LINK_CREATE,
        data=json.dumps({"path": remote_path}).encode("utf-8"),
        headers=headers, method="POST"
    )
    if code == 200:
        try:
            return json.loads(body.decode("utf-8")).get("url","")
        except Exception:
            pass
    # sinon lister
    body, code = http_json(
        LINK_LIST,
        data=json.dumps({"path": remote_path, "direct_only": True}).encode("utf-8"),
        headers=headers, method="POST"
    )
    if code == 200:
        try:
            j = json.loads(body.decode("utf-8"))
            links = j.get("links") or []
            if links:
                return links[0].get("url","")
        except Exception:
            pass
    return ""

def main():
    p = argparse.ArgumentParser(description="Upload to Dropbox (refresh token only) and write share link.")
    p.add_argument("--file", required=True, help="Chemin du fichier local à uploader")
    p.add_argument("--remote-dir", dest="remote_dir", default="/horror", help="Dossier Dropbox de destination")
    p.add_argument("--out-link", dest="out_link", default="final_video/dropbox_link.txt", help="Fichier où écrire le lien")
    args = p.parse_args()

    local = pathlib.Path(args.file)
    if not local.exists() or not local.stat().st_size:
        sys.stderr.write(f"[dropbox] Fichier manquant/vide: {local}\n")
        sys.exit(1)

    app_key    = os.getenv("DROPBOX_APP_KEY", "")
    app_secret = os.getenv("DROPBOX_APP_SECRET", "")
    refresh    = os.getenv("DROPBOX_REFRESH_TOKEN", "")
    if not (app_key and app_secret and refresh):
        sys.stderr.write("[dropbox] Variables manquantes: DROPBOX_APP_KEY / DROPBOX_APP_SECRET / DROPBOX_REFRESH_TOKEN\n")
        sys.exit(1)

    access_token = oauth_refresh(app_key, app_secret, refresh)
    if not access_token:
        sys.stderr.write("[dropbox] Impossible d’obtenir un access_token via refresh token.\n")
        sys.exit(1)

    ts = time.strftime("%Y%m%d_%H%M%S")
    remote_dir = args.remote_dir.rstrip("/")
    remote_dir = remote_dir if remote_dir else ""
    remote_path = f"{remote_dir}/{ts}_{local.name}" if remote_dir else f"/{ts}_{local.name}"

    size = local.stat().st_size
    if size <= SMALL_LIMIT:
        code, body = upload_small(access_token, local, remote_path)
    else:
        code, body = upload_large(access_token, local, remote_path)

    if code < 200 or code >= 300:
        sys.stderr.write(f"[dropbox] Upload échec http={code} body={body[:400]!r}\n")
        sys.exit(1)

    url = ensure_shared_link(access_token, remote_path)
    if not url:
        sys.stderr.write("[dropbox] Impossible d’obtenir un lien partageable.\n")
        sys.exit(1)

    # Forcer lien direct (?dl=1)
    if url.endswith("?dl=0"):
        url = url[:-5] + "?dl=1"
    elif "?dl=0" in url:
        url = url.replace("?dl=0", "?dl=1")

    out = pathlib.Path(args.out_link)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(url + "\n", encoding="utf-8")
    print(f"[dropbox] Lien direct: {url}")

if __name__ == "__main__":
    main()