from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse
import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.request
import webbrowser

import keyring
from keyring.errors import KeyringError

# Claude Code と同じ OAuth クライアントでログインし、アプリ専用のトークンを発行する
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTHORIZE_URL = "https://claude.com/cai/oauth/authorize"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
SCOPE = "user:profile"
SERVICE = "LLM Usages"
ACCOUNT = "Claude"
LOGIN_TIMEOUT = 300

lock = threading.Lock()


def encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def load():
    try:
        value = keyring.get_password(SERVICE, ACCOUNT)
        return json.loads(value) if value else None
    except (KeyringError, ValueError):
        return None


def save(reply, refresh_token=None):
    tokens = {"access_token": reply["access_token"],
              "refresh_token": reply.get("refresh_token") or refresh_token,
              "expires_at": time.time() + int(reply.get("expires_in", 3600))}
    keyring.set_password(SERVICE, ACCOUNT, json.dumps(tokens))
    return tokens


def post(body):
    request = urllib.request.Request(TOKEN_URL, data=json.dumps(body).encode(), method="POST", headers={
        "Content-Type": "application/json", "User-Agent": "LLM-Usages/0.1"})
    with urllib.request.urlopen(request, timeout=30) as reply:
        return json.load(reply)


def refresh(tokens):
    try:
        reply = post({"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
                      "client_id": CLIENT_ID, "scope": SCOPE})
    except urllib.error.HTTPError as error:
        if error.code in (400, 401, 403):
            raise PermissionError() from None
        raise RuntimeError(f"Claude のログイン情報を更新できませんでした (HTTP {error.code})") from None
    return save(reply, tokens["refresh_token"])


def access_token(force_refresh=False):
    with lock:
        tokens = load()
        if not tokens:
            raise PermissionError()
        if force_refresh or tokens["expires_at"] - 60 < time.time():
            tokens = refresh(tokens)
        return tokens["access_token"]


def login():
    verifier = encode(secrets.token_bytes(32))
    state = encode(secrets.token_bytes(32))
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path != "/callback" or query.get("state") != state:
                self.send_error(404)
                return
            result.update(query)
            body = "ログインしました。このタブを閉じてください".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("localhost", 0), Handler)
    server.timeout = 1
    redirect_uri = f"http://localhost:{server.server_port}/callback"
    webbrowser.open(AUTHORIZE_URL + "?" + urlencode({
        "code": "true", "client_id": CLIENT_ID, "response_type": "code", "redirect_uri": redirect_uri, "scope": SCOPE,
        "code_challenge": encode(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256",
        "state": state}))
    deadline = time.monotonic() + LOGIN_TIMEOUT
    try:
        while not result and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if not result:
        raise RuntimeError("Claude のログインがタイムアウトしました")
    if "code" not in result:
        raise RuntimeError("Claude のログインが完了しませんでした")
    try:
        reply = post({"grant_type": "authorization_code", "code": result["code"], "redirect_uri": redirect_uri,
                      "client_id": CLIENT_ID, "code_verifier": verifier, "state": state})
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Claude のログインに失敗しました (HTTP {error.code})") from None
    with lock:
        save(reply)
