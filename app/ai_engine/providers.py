"""Pluggable online AI providers (stdlib only). Two wire formats cover most
services: OpenAI-compatible (OpenAI, OpenRouter, Ollama/LM Studio locally...)
and Anthropic Messages."""
from __future__ import annotations
import json
import socket
import urllib.error
import urllib.request

PROVIDERS = {"openai_compatible": "سازگار با OpenAI (شامل Ollama محلی)", "anthropic": "Anthropic"}
PRESET_URLS = {"openai_compatible": "https://api.openai.com/v1", "anthropic": "https://api.anthropic.com"}


class AiError(Exception):
    """Message is user-facing (Persian)."""


def http_post_json(url: str, headers: dict, payload: dict, timeout: int = 45) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        msgs = {401: "کلید API نامعتبر است.", 403: "این کلید دسترسی لازم را ندارد.",
                404: "آدرس سرویس یا نام مدل اشتباه است.", 429: "سقف مصرف سرویس‌دهنده پر شده است؛ بعداً تلاش کنید."}
        base = msgs.get(e.code, "خطای سرور سرویس‌دهنده." if e.code >= 500 else f"درخواست رد شد (کد {e.code}).")
        raise AiError(f"{base} {body}".strip())
    except (socket.timeout, TimeoutError):
        raise AiError("پاسخی در زمان مقرر نیامد.")
    except urllib.error.URLError as e:
        raise AiError(f"اتصال برقرار نشد (اینترنت یا آدرس را بررسی کنید): {e.reason}")
    except (ValueError, UnicodeDecodeError):
        raise AiError("پاسخ سرویس‌دهنده قابل خواندن نبود.")


def complete(provider: str, base_url: str, model: str, api_key: str, system: str, user: str,
             max_tokens: int = 800, transport=http_post_json) -> str:
    base = base_url.rstrip("/")
    if provider == "anthropic":
        data = transport(f"{base}/v1/messages",
                         {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                         {"model": model, "max_tokens": max_tokens, "system": system,
                          "messages": [{"role": "user", "content": user}]})
        try:
            return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text").strip()
        except (KeyError, TypeError):
            raise AiError("ساختار پاسخ Anthropic نامعتبر بود.")
    if provider == "openai_compatible":
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        data = transport(f"{base}/chat/completions", headers,
                         {"model": model, "max_tokens": max_tokens, "temperature": 0.3,
                          "messages": [{"role": "system", "content": system},
                                       {"role": "user", "content": user}]})
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError, AttributeError):
            raise AiError("ساختار پاسخ سرویس‌دهنده نامعتبر بود.")
    raise AiError("نوع ارائه‌دهنده نامعتبر است.")
