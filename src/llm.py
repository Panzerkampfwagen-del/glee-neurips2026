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

_enabled = bool(os.environ.get("GROQ_API_KEY")) and \
    os.environ.get("GLEE_USE_LLM", "1") == "1"

_lock = threading.Lock()
_call_times: deque[float] = deque()
RPM_CAP = 24


def enabled() -> bool:
    return _enabled


def available(n: int = 1) -> bool:
    """True if n calls can be made right now without breaching RPM cap."""
    now = time.time()
    with _lock:
        while _call_times and now - _call_times[0] > 60.0:
            _call_times.popleft()
        return len(_call_times) + n <= RPM_CAP


def _take():
    now = time.time()
    with _lock:
        while _call_times and now - _call_times[0] > 60.0:
            _call_times.popleft()
        if len(_call_times) >= RPM_CAP:
            return False
        _call_times.append(now)
        return True


def chat(messages: list[dict], model: str | None = None,
         timeout: float = 10.0, max_tokens: int = 300) -> str | None:
    if not _enabled or not _take():
        return None
    try:
        resp = requests.post(API_URL, timeout=timeout, headers={
            "Authorization": f"Bearer {os.environ['GROQ_API_KEY']}",
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
