from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import json
import math
import os
import queue
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request


@dataclass
class Window:
    name: str
    used: float
    reset: datetime | None


@dataclass
class Usage:
    provider: str
    windows: list[Window] = field(default_factory=list)
    error: str = ""
    captured: datetime = field(default_factory=lambda: datetime.now().astimezone())


def percent(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("使用率の形式を確認できません")
    return max(0.0, min(100.0, number))


def executable(name):
    found = shutil.which(name + ".exe") or shutil.which(name)
    if found:
        return found
    if name == "codex":
        paths = sorted((Path.home() / "AppData/Local/OpenAI/Codex/bin").glob("*/codex.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
    else:
        paths = [Path.home() / ".local/bin/claude.exe"]
    return next((str(p) for p in paths if p.exists()), None)


def codex_usage():
    command = executable("codex")
    if not command:
        raise RuntimeError("Codex をインストールしてログインしてください")
    process = subprocess.Popen([command, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    messages = queue.Queue()

    def read():
        for line in process.stdout:
            try:
                messages.put(json.loads(line))
            except ValueError:
                continue
        messages.put(None)

    threading.Thread(target=read, daemon=True).start()

    def send(data):
        process.stdin.write(json.dumps(data) + "\n")
        process.stdin.flush()

    def response(request_id):
        deadline = time.monotonic() + 25
        while True:
            try:
                msg = messages.get(timeout=max(.01, deadline - time.monotonic()))
            except queue.Empty:
                raise RuntimeError("Codex の応答がタイムアウトしました") from None
            if msg is None:
                raise RuntimeError("Codex との接続が終了しました")
            if msg.get("id") != request_id:
                continue
            if "error" in msg:
                raise RuntimeError("Codex の取得に失敗しました。ログイン状態を確認してください")
            return msg["result"]

    try:
        send({"method": "initialize", "id": 1, "params": {"clientInfo": {"name": "llm_usages", "title": "LLM Usages", "version": "0.1.0"}}})
        response(1)
        send({"method": "initialized", "params": {}})
        send({"method": "account/rateLimits/read", "id": 2})
        result = response(2)
        buckets = result.get("rateLimitsByLimitId")
        if not buckets:
            buckets = {"codex": result.get("rateLimits") or {}}
        windows = []
        for key, bucket in buckets.items():
            for slot in ("primary", "secondary"):
                item = bucket.get(slot)
                if not item or item.get("usedPercent") is None:
                    continue
                minutes = item.get("windowDurationMins")
                duration = "週間" if minutes == 10080 else f"{minutes / 60:g} 時間" if minutes else "使用枠"
                label = duration if len(buckets) == 1 else f"{bucket.get('limitName') or key} / {duration}"
                reset = item.get("resetsAt")
                windows.append(Window(label, percent(item["usedPercent"]), datetime.fromtimestamp(reset).astimezone() if reset else None))
        if not windows:
            raise RuntimeError("使用率が提供されていません")
        return Usage("Codex", windows)
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        process.stdin.close()
        process.stdout.close()


def claude_usage(credentials_path=""):
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
    path = Path(credentials_path).expanduser() if credentials_path else config_dir / ".credentials.json"
    if not path.exists():
        raise RuntimeError("Claude Code にログインしてください")
    try:
        credentials = json.loads(path.read_text(encoding="utf-8"))
        token = credentials["claudeAiOauth"]["accessToken"]
    except (ValueError, KeyError, TypeError):
        raise RuntimeError("Claude のログイン情報を確認できません") from None
    request = urllib.request.Request("https://api.anthropic.com/api/oauth/usage", headers={
        "Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20", "User-Agent": "LLM-Usages/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=25) as reply:
            data = json.load(reply)
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise RuntimeError("Claude Code で再ログインしてください") from None
        if error.code == 429:
            raise RuntimeError("取得が制限されています。しばらく待って更新してください") from None
        raise RuntimeError(f"Claude の取得に失敗しました (HTTP {error.code})") from None
    windows = []
    for key, label in (("five_hour", "5 時間"), ("seven_day", "週間"), ("seven_day_sonnet", "Sonnet / 週間"), ("seven_day_opus", "Opus / 週間")):
        item = data.get(key)
        if not item or item.get("utilization") is None:
            continue
        reset = item.get("resets_at")
        windows.append(Window(label, percent(item["utilization"]), datetime.fromisoformat(reset.replace("Z", "+00:00")).astimezone() if reset else None))
    if not windows:
        raise RuntimeError("使用率が提供されていません")
    return Usage("Claude", windows)


def fetch(provider, credentials_path=""):
    try:
        return codex_usage() if provider == "Codex" else claude_usage(credentials_path)
    except Exception as error:
        message = str(error) if isinstance(error, RuntimeError) else "取得に失敗しました。接続と設定を確認してください"
        return Usage(provider, error=message)
