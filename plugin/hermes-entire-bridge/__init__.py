"""hermes-entire-bridge — forward Hermes session lifecycle to Entire.

Registers Hermes plugin hooks, maintains a Claude-style JSONL transcript
under ~/.entire-hermes/sessions/<repo-slug>/<session_id>.jsonl (the path the
entire-agent-hermes integration binary resolves), and fires-and-forgets
`entire hooks hermes <hook>` with a JSON payload on stdin whenever a
checkpoint-worthy lifecycle event happens.

Design constraints:
  * Never block or slow the agent loop. All forwarding happens in daemon
    threads; every callback is wrapped in try/except and fails open.
  * Zero effect when Entire isn't in play: if the `entire` binary is missing
    or the current repo has no enabled .entire/settings.json, we do nothing.
    Detection result is cached per directory (TTL) and cheap.
  * Kill switch: ENTIRE_HERMES_BRIDGE=0 in the environment disables all hooks.

Turn mapping (Hermes -> Entire):
  on_session_start                  -> session-start      (Type 1 SessionStart)
  post_llm_call (first time/turn)   -> user-prompt-submit (Type 2 TurnStart)
  post_llm_call (end of same call)  -> stop               (Type 3 TurnEnd)
  post_tool_call                    -> transcript line only (no forward)
  on_session_end / on_session_reset -> session-end        (Type 5 SessionEnd)

Transcript lines (consumed by entire-agent-hermes extract-* subcommands):
  {"type":"user","timestamp":...,"message":{"content":"..."}}
  {"type":"assistant","timestamp":...,"message":{"content":[{"type":"text","text":...}]}}
  {"type":"tool","timestamp":...,"tool_name":"write_file","tool_input":{...}}
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

BRIDGE_DIR = Path.home() / ".entire-hermes"
SESSIONS_DIR = BRIDGE_DIR / "sessions"
LOG_PATH = BRIDGE_DIR / "bridge.log"
FORWARD_TIMEOUT_S = 25

# Tool calls worth recording in the transcript for modified-file extraction.
FILE_TOOLS = {"write_file", "patch", "skill_manage"}
PATH_KEYS = ("path", "file_path")

_state_lock = threading.Lock()
_seen_turns: dict[str, str] = {}        # session_id -> last forwarded turn_id
_entire_cache: dict[str, tuple[float, bool]] = {}  # dir -> (monotonic, enabled)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(msg: str) -> None:
    try:
        BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write("%s %s\n" % (_now(), msg))
    except OSError:
        pass


def _repo_root(cwd: str) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd or None, capture_output=True, text=True, timeout=5,
        )
        root = out.stdout.strip()
        return root if out.returncode == 0 and root else ""
    except Exception:
        return ""


def _repo_slug(repo_path: str) -> str:
    # MUST match repo_slug() in bin/entire-agent-hermes.
    abs_path = os.path.abspath(repo_path)
    mangled = abs_path.replace(os.sep, "-").strip("-")
    digest = hashlib.sha256(abs_path.encode()).hexdigest()[:8]
    return "%s-%s" % (mangled, digest)


def _entire_enabled(cwd: str) -> bool:
    """True when `entire` is on PATH and an upward walk finds an enabled
    .entire/settings.json. Cached per start dir for 60s."""
    if os.environ.get("ENTIRE_HERMES_BRIDGE") == "0":
        return False
    start = cwd or os.getcwd()
    key = start
    now = time.monotonic()
    hit = _entire_cache.get(key)
    if hit and now - hit[0] < 60:
        return hit[1]
    ok = False
    try:
        if shutil.which("entire"):
            d = Path(start)
            while d != d.parent:
                settings = d / ".entire" / "settings.json"
                if settings.exists():
                    try:
                        ok = bool(json.loads(settings.read_text()).get("enabled", True))
                    except (OSError, ValueError):
                        ok = False
                    break
                d = d.parent
    except Exception:
        ok = False
    _entire_cache[key] = (now, ok)
    return ok


def _session_file(cwd: str, session_id: str) -> "Path | None":
    root = _repo_root(cwd)
    if not root or not session_id:
        return None
    return SESSIONS_DIR / _repo_slug(root) / (session_id + ".jsonl")


def _append_line(path: Path, obj: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    except OSError as e:
        _log("append failed %s: %s" % (path, e))


def _forward(hook: str, payload: dict) -> None:
    """Fire-and-forget `entire hooks hermes <hook>` with payload on stdin.
    Runs in a daemon thread so the agent loop never waits on Entire."""
    def run():
        try:
            proc = subprocess.run(
                ["entire", "hooks", "hermes", hook],
                input=json.dumps(payload, ensure_ascii=False, default=str),
                capture_output=True, text=True,
                timeout=FORWARD_TIMEOUT_S,
                cwd=payload.get("cwd") or None,
            )
            if proc.returncode != 0:
                _log("forward %s rc=%d stderr=%s" % (
                    hook, proc.returncode, (proc.stderr or "")[:400]))
        except FileNotFoundError:
            _entire_cache.clear()  # binary vanished; re-detect next time
        except Exception as e:
            _log("forward %s error: %s" % (hook, e))
    threading.Thread(target=run, daemon=True).start()


def _base_payload(kwargs: dict) -> dict:
    payload = {
        "hook_event_name": kwargs.get("hook_event_name") or "",
        "session_id": kwargs.get("session_id") or "",
        "cwd": os.getcwd(),
        "profile": os.environ.get("HERMES_PROFILE") or "default",
        "timestamp": _now(),
    }
    extra = {k: v for k, v in kwargs.items()
             if k not in ("conversation_history", "session_id", "hook_event_name")}
    payload["extra"] = extra
    return payload


# --- hook callbacks ---------------------------------------------------------

def _on_session_start(**kwargs):
    try:
        cwd = os.getcwd()
        if not _entire_enabled(cwd):
            return
        sid = kwargs.get("session_id") or ""
        path = _session_file(cwd, sid)
        if not path:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)  # CLI rejects missing session_ref
        payload = _base_payload(kwargs)
        payload.update({"model": kwargs.get("model") or "",
                        "transcript_path": str(path)})
        _forward("session-start", payload)
    except Exception as e:
        _log("on_session_start: %s" % e)


def _on_post_llm_call(**kwargs):
    try:
        cwd = os.getcwd()
        if not _entire_enabled(cwd):
            return
        sid = kwargs.get("session_id") or ""
        turn_id = str(kwargs.get("turn_id") or kwargs.get("task_id") or "")
        path = _session_file(cwd, sid)
        if not path:
            return
        user_message = kwargs.get("user_message") or ""
        assistant = kwargs.get("assistant_response") or ""
        model = kwargs.get("model") or ""

        first = True
        with _state_lock:
            if _seen_turns.get(sid) == turn_id:
                first = False
            else:
                _seen_turns[sid] = turn_id

        if first and user_message:
            _append_line(path, {"type": "user", "timestamp": _now(),
                                "message": {"content": user_message}})
            payload = _base_payload(kwargs)
            payload.update({"user_prompt": user_message, "model": model,
                            "transcript_path": str(path)})
            # conversation_history can be megabytes; don't ship it to the CLI.
            payload["extra"].pop("conversation_history", None)
            _forward("user-prompt-submit", payload)

        _append_line(path, {"type": "assistant", "timestamp": _now(),
                            "message": {"content": [{"type": "text",
                                                     "text": assistant}]}})
        payload = _base_payload(kwargs)
        payload.update({"model": model, "transcript_path": str(path)})
        payload["extra"].pop("conversation_history", None)
        _forward("stop", payload)
    except Exception as e:
        _log("post_llm_call: %s" % e)


def _on_post_tool_call(**kwargs):
    try:
        cwd = os.getcwd()
        if not _entire_enabled(cwd):
            return
        tool = kwargs.get("tool_name") or ""
        args = kwargs.get("args") or {}
        if tool not in FILE_TOOLS or not isinstance(args, dict):
            return
        sid = kwargs.get("session_id") or ""
        path = _session_file(cwd, sid)
        if not path:
            return
        _append_line(path, {
            "type": "tool", "timestamp": _now(), "tool_name": tool,
            "tool_input": {k: args.get(k) for k in PATH_KEYS if args.get(k)},
            "duration_ms": kwargs.get("duration_ms"),
        })
    except Exception as e:
        _log("post_tool_call: %s" % e)


def _on_session_end(**kwargs):
    try:
        cwd = os.getcwd()
        if not _entire_enabled(cwd):
            return
        sid = kwargs.get("session_id") or ""
        payload = _base_payload(kwargs)
        path = _session_file(cwd, sid)
        if path:
            payload["transcript_path"] = str(path)
        _forward("session-end", payload)
        with _state_lock:
            _seen_turns.pop(sid, None)
    except Exception as e:
        _log("on_session_end: %s" % e)


def _on_session_reset(**kwargs):
    # /new rotates the session; close the old one, a fresh session-start will
    # arrive for the new id.
    _on_session_end(**kwargs)


# --- plugin registration -----------------------------------------------------

def register(ctx) -> None:
    ctx.register_hook("on_session_start", _on_session_start)
    ctx.register_hook("post_llm_call", _on_post_llm_call)
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_hook("on_session_end", _on_session_end)
    ctx.register_hook("on_session_reset", _on_session_reset)
