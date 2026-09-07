from __future__ import annotations

import json
import urllib.error
import urllib.request

from .core import WorkbenchError


class OllamaEmbedder:
    def __init__(self, model: str = "embeddinggemma", base_url: str = "http://127.0.0.1:11434") -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise WorkbenchError(
                "无法连接本机 Ollama。请启动 Ollama 并运行：ollama pull embeddinggemma"
            ) from exc
        vectors = data.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise WorkbenchError("Ollama 返回了无效的嵌入结果")
        return [[float(value) for value in vector] for vector in vectors]

    def available_models(self) -> list[str]:
        try:
            with urllib.request.urlopen(f"{self.base_url}/api/tags", timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise WorkbenchError("Ollama 未启动或本地 API 不可用") from exc
        return [str(item.get("name", "")) for item in data.get("models", [])]
