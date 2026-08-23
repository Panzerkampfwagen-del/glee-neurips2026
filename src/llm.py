"""Thin Groq client: global rate limiting, timeouts, defensive parsing.

Free-tier budgets are tight, so all callers go through take() — simulation
waves pre-check availability and shrink N rather than queue-jump.
"""

import json
import os
import threading
import time
from collections import deque

import requests

API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL_FAST = os.environ.get("GLEE_LLM_FAST", "openai/gpt-oss-20b")
MODEL_STRONG = os.environ.get("GLEE_LLM_STRONG", "openai/gpt-oss-120b")

_keys = [k for k in (os.environ.get("GROQ_API_KEY"),
                     os.environ.get("GROQ_API_KEY_2")) if k]
_enabled = bool(_keys) and os.environ.get("GLEE_USE_LLM", "1") == "1"

_lock = threading.Lock()
_buckets: dict[str, deque] = {k: deque() for k in _keys}
_rr = 0
RPM_CAP = 24  # per key


def enabled() -> bool:
    return _enabled


def available(n: int = 1) -> bool:
    """True if n calls can be made right now across all key buckets."""
    now = time.time()
    with _lock:
        for q in _buckets.values():
            while q and now - q[0] > 60.0:
                q.popleft()
        return sum(len(q) for q in _buckets.values()) + n <= RPM_CAP * max(1, len(_buckets))


def _take() -> str | None:
    """Round-robin over keys; first bucket with headroom wins."""
    global _rr
    now = time.time()
    with _lock:
        keys = list(_buckets)
        if not keys:
            return None
        for i in range(len(keys)):
            key = keys[(_rr + i) % len(keys)]
            q = _buckets[key]
            while q and now - q[0] > 60.0:
                q.popleft()
            if len(q) < RPM_CAP:
                q.append(now)
                _rr = (_rr + i + 1) % len(keys)
                return key
        return None


def chat(messages: list[dict], model: str | None = None,
         timeout: float = 10.0, max_tokens: int = 300) -> str | None:
    if not _enabled:
        return None
    api_key = _take()
    if not api_key:
        return None
    try:
        resp = requests.post(API_URL, timeout=timeout, headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }, json={
            "model": model or MODEL_FAST,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.4,
        })
        if resp.status_code != 200:
            return None
        return resp.json()["choices"][0]["message"]["content"]
    except Exception:
        return None


def json_chat(messages: list[dict], model: str | None = None,
              timeout: float = 10.0, max_tokens: int = 300) -> dict | None:
    text = chat(messages, model=model, timeout=timeout, max_tokens=max_tokens)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        import re
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None
