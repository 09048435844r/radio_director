"""Mac Studio Proxy (port 11435) 経由で vLLM (Qwen3.5-122B) を叩くクライアント。

Ollama 形式 /api/generate を投げると、Proxy が OpenAI 形式
/v1/chat/completions に変換して GX10:8000 の vLLM に転送する。
format='json' を渡すと vLLM の guided decoding が有効になる。
仕様 §0.2 / §13.2 / §22 を参照。
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:11435"
DEFAULT_MODEL = "qwen3.5-122b"
DEFAULT_TIMEOUT_SEC = 1800


class LLMRequestError(RuntimeError):
    """LLM への HTTP 呼び出しが失敗した場合に投げる。"""


class LLMClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_sec = timeout_sec

    @classmethod
    def from_env(cls) -> "LLMClient":
        return cls(
            base_url=os.environ.get("RADIO_DIRECTOR_LLM_BASE_URL", DEFAULT_BASE_URL),
            model=os.environ.get("RADIO_DIRECTOR_LLM_MODEL", DEFAULT_MODEL),
            timeout_sec=int(
                os.environ.get("RADIO_DIRECTOR_LLM_TIMEOUT", str(DEFAULT_TIMEOUT_SEC))
            ),
        )

    def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.5,
        max_tokens: int = 4096,
        json_mode: bool = True,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if json_mode:
            payload["format"] = "json"

        url = f"{self.base_url}/api/generate"
        logger.info(
            "LLM request: model=%s prompt_chars=%d max_tokens=%d json_mode=%s",
            self.model,
            len(prompt),
            max_tokens,
            json_mode,
        )
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout_sec)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise LLMRequestError(
                f"LLM request failed (url={url}, model={self.model}): {exc}"
            ) from exc

        data = resp.json()
        text = data.get("response", "")
        logger.info("LLM response: chars=%d", len(text))
        return text
