#!/usr/bin/env python3
import os, sys, json, time, pathlib, urllib.request, urllib.parse, base64, subprocess, tempfile

import argparse
ap = argparse.ArgumentParser()
ap.add_argument("--file", required=True, help="Fichier local à uploader")
ap.add_argument("--remote-dir", default="/horror")
ap.add_argument("--out-link", default="final_video/dropbox_link.txt")
args = ap.parse_args()

fpath = pathlib.Path(args.file)
if not fpath.exists() or not fpath.stat().st_size:
    print(f"Fichier introuvable/vide: {fpath}", file=sys.stderr); sys.exit(1)

out_link = pathlib.Path(args.out_link)
out_link.parent.mkdir(parents=True, exist_ok=True)

APP_KEY = os.environ.get("DROPBOX_APP_KEY","").strip()
APP_SECRET = os.environ.get("DROPBOX_APP_SECRET","").strip()
REFRESH = os.environ.get("DROPBOX_REFRESH_TOKEN","").strip()
ACCESS = os.environ.get("DROPBOX_ACCESS_TOKEN","").strip()

def token_from_refresh():
    if not (APP_KEY and APP_SECRET and REFRESH):
        return None
    data = urllib.parse.urlencode({
        "grant_type":"refresh_token",
        "refresh_token": REFRESH
    }).encode("utf-8")
    basic = base64.b64encode(f"{APP_KEY}:{APP_SECRET}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        "https://api.dropboxapi.com/oauth2/token",
        data=data,
        headers={"Authorization": f"Basic {basic}", "Content-Type":"application/x-www-form-urlencoded"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            j = json.loads(resp.read().decode("utf-8"))
            return j.get("access_token")
    except Exception as e:
        print(f"refresh_token échec: {e}", file=sys.stderr)
        return None

token = token_from_refresh() or ACCESS
if not token:
    print("Aucun token Dropbox dispo (refresh recommandé ou access token simple).", file=sys.stderr)
    sys.exit(1)

remote_dir = args.remote_dir if args.remote_dir.startswith("/") else "/"+args.remote_dir
ts = time.strftime("%Y%m%d_%H%M%S")
remote_path = f"{remote_dir}/{ts}_{fpath.name}"

size = fpath.stat().st_size
def http_json(req):
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))

def upload_simple():
    api_arg = json.dumps({"path": remote_path, "mode":"add", "autorename":True, "mute":False})
    req = urllib.request.Request(
        "https://content.dropboxapi.com/2/files/upload",
        data=fpath.read_bytes(),
        headers={
            "Authorization": f"Bearer {token}",
            "Dropbox-API-Arg": api_arg,
            "Content-Type": "application/octet-stream"
        }, method="POST"
    )
    return http_json(req)

def upload_chunked():
    # start
    req = urllib.request.Request(
        "https://content.dropboxapi.com/2/files/upload_session/start",
        data=b"",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
            "Dropbox-API-Arg": json.dumps({"close": False})
        }, method="POST"
    )
    start = http_json(req)
    sid = start["session_id"]
    chunk = 15*1024*1024
    with open(fpath,"rb") as fh:
        off = 0
        while True:
            data = fh.read(chunk)
            if not data: break
            arg = {"cursor":{"session_id":sid,"offset":off},"close": False}
            req = urllib.request.Request(
                "https://content.dropboxapi.com/2/files/upload_session/append_v2",
                data=data,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type":"application/octet-stream",
                    "Dropbox-API-Arg": json.dumps(arg)
                }, method="POST"
            )
            urllib.request.urlopen(req, timeout=120).read()
            off += len(data)
    commit = {
        "cursor":{"session_id":sid,"offset": size},
        "commit":{"path":remote_path,"mode":"add","autorename":True,"mute":False}
    }
    req = urllib.request.Request(
        "https://content.dropboxapi.com/2/files/upload_session/finish",
        data=b"",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":"application/octet-stream",
            "Dropbox-API-Arg": json.dumps(commit)
        }, method="POST"
    )
    return http_json(req)

try:
    if size <= 150*1024*1024:
        up = upload_simple()
    else:
        up = upload_chunked()
except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8","ignore")
    print(f"Upload HTTPError: {e.code} {body}", file=sys.stderr)
    sys.exit(1)

# create (or fetch) shared link
def get_or_create_link():
    payload = json.dumps({"path": remote_path}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.dropboxapi.com/2/sharing/create_shared_link_with_settings",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type":"application/json"},
        method="POST"
    )
    try:
        j = http_json(req); return j.get("url","")
    except urllib.error.HTTPError as e:
        # peut déjà exister
        payload2 = json.dumps({"path":remote_path,"direct_only":True}).encode("utf-8")
        req2 = urllib.request.Request(
            "https://api.dropboxapi.com/2/sharing/list_shared_links",
            data=payload2,
            headers={"Authorization": f"Bearer {token}", "Content-Type":"application/json"},
            method="POST"
        )
        j2 = http_json(req2)
        links = j2.get("links") or []
        if links: return links[0].get("url","")
        raise

url = get_or_create_link()
if not url:
    print("Pas de lien partagé renvoyé par Dropbox.", file=sys.stderr); sys.exit(1)

# transformer ?dl=0 en ?dl=1
if url.endswith("?dl=0"):
    url = url[:-5] + "?dl=1"

out_link.write_text(url+"\n", encoding="utf-8")
print(f"[dropbox] upload OK → {remote_path}\n[dropbox] link: {url}")