"""Minimal OpenAI API client using only the Python standard library.

The app keeps working without an API key. When OPENAI_API_KEY is present in
.env or process environment, chat_json/chat_text call OpenAI's Chat Completions
API and return structured results for the RAG agent.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def load_env() -> dict[str, str]:
    env = dict(os.environ)
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env


def settings() -> dict[str, Any]:
    env = load_env()
    key = (env.get("OPENAI_API_KEY") or env.get("AI_API_KEY") or "").strip()
    base_url = (env.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    model = (env.get("AI_MODEL") or "gpt-4.1-mini").strip()
    return {
        "enabled": bool(key),
        "provider": env.get("AI_PROVIDER", "openai"),
        "model": model,
        "base_url": base_url,
        "api_key": key,
        "mode": "openai-live" if key else "local-rag-fallback",
    }


def public_status(used: bool = False, error: Optional[str] = None) -> dict[str, Any]:
    s = settings()
    out = {
        "enabled": bool(s["enabled"]),
        "provider": s["provider"],
        "model": s["model"],
        "mode": "openai-live" if s["enabled"] else "local-rag-fallback",
        "used": bool(used),
    }
    if error:
        out["error"] = error
    return out


def chat_completion(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    max_tokens: int = 1400,
    json_mode: bool = False,
    timeout: int = 35,
) -> dict[str, Any]:
    s = settings()
    if not s["enabled"]:
        return {"ok": False, "error": "OPENAI_API_KEY is not configured", "status": public_status(False)}

    payload: dict[str, Any] = {
        "model": s["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    req = urllib.request.Request(
        f"{s['base_url']}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {s['api_key']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {"ok": True, "content": content, "raw": data, "status": public_status(True)}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")[:800]
        return {"ok": False, "error": f"OpenAI HTTP {e.code}: {body}", "status": public_status(False, f"HTTP {e.code}")}
    except Exception as e:
        return {"ok": False, "error": str(e), "status": public_status(False, str(e))}


def parse_json_object(text: str) -> Optional[dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start:end + 1])
            return data if isinstance(data, dict) else None
        except Exception:
            return None
    return None


def chat_json(messages: list[dict[str, str]], *, temperature: float = 0.1, max_tokens: int = 1600) -> dict[str, Any]:
    res = chat_completion(messages, temperature=temperature, max_tokens=max_tokens, json_mode=True)
    if not res.get("ok"):
        return res
    data = parse_json_object(res.get("content", ""))
    if data is None:
        return {"ok": False, "error": "model did not return valid JSON", "content": res.get("content"), "status": res.get("status")}
    res["json"] = data
    return res


def chat_text(messages: list[dict[str, str]], *, temperature: float = 0.2, max_tokens: int = 1200) -> dict[str, Any]:
    return chat_completion(messages, temperature=temperature, max_tokens=max_tokens, json_mode=False)
