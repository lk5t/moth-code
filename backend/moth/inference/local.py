"""Local inference: run an exported MOTH model on this PC (CUDA or CPU)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

from moth.model.chat_format import Message, encode_chat
from moth.model.generation import GenerationParams, GenerationStats, generate_stream


class NoModelLoaded(RuntimeError):
    pass


class LocalInference:
    name = "local"

    def __init__(self, models_dir: Path):
        self.models_dir = Path(models_dir)
        self._lock = threading.RLock()
        self.model = None
        self.tokenizer = None
        self.manifest: dict[str, Any] | None = None
        self.device = "cpu"
        self.model_id: str | None = None

    def status(self) -> dict[str, Any]:
        if self.model is None:
            return {"loaded": False}
        return {"loaded": True, "id": self.model_id, "name": self.manifest["name"], "device": self.device,
                "params": self.manifest["params"], "context_length": self.manifest["context_length"]}

    def available(self) -> bool:
        return self.model is not None

    def load(self, model_id: str, device: str = "auto") -> dict[str, Any]:
        from moth.model.registry import load_model
        from moth.training.trainer import pick_device

        dev = pick_device(device)
        with self._lock:
            model, tok, manifest = load_model(self.models_dir / model_id, device=dev)
            self.model, self.tokenizer, self.manifest, self.device, self.model_id = model, tok, manifest, dev, model_id
        return self.status()

    def unload(self) -> None:
        with self._lock:
            self.model = self.tokenizer = self.manifest = None
            self.model_id = None
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

    def chat(self, messages: list[Message], params: GenerationParams, on_text: Callable[[str], None],
             cancel_event: threading.Event | None = None) -> GenerationStats:
        with self._lock:
            if self.model is None:
                raise NoModelLoaded("No MOTH model is loaded. Train and export a model, then load it in Models.")
            ids, _ = encode_chat(self.tokenizer, messages, add_generation_prompt=True)
            stats = GenerationStats()
            for piece in generate_stream(self.model, self.tokenizer, ids, params, cancel_event=cancel_event,
                                         stats=stats):
                on_text(piece)
            return stats

    def complete(self, prompt: str, params: GenerationParams, cancel_event: threading.Event | None = None) -> tuple[str, GenerationStats]:
        with self._lock:
            if self.model is None:
                raise NoModelLoaded("No MOTH model is loaded.")
            ids = [self.tokenizer.bos_id] + self.tokenizer.encode(prompt, allow_special=True)
            stats = GenerationStats()
            out = "".join(generate_stream(self.model, self.tokenizer, ids, params, cancel_event=cancel_event,
                                          stats=stats))
            return out, stats


class LocalAgentLLM:
    """Adapter exposing the loaded local MOTH model to the agent engine."""

    def __init__(self, engine: LocalInference):
        if engine.model is None:
            raise NoModelLoaded("No MOTH model is loaded. Load a model under Models before starting a task.")
        self.engine = engine
        self.name = engine.manifest["name"]
        self.context_length = engine.manifest["context_length"]

    def count_tokens(self, messages: list[Message]) -> int:
        ids, _ = encode_chat(self.engine.tokenizer, messages)
        return len(ids)

    def generate(self, messages: list[Message], params: GenerationParams, cancel: threading.Event) -> str:
        parts: list[str] = []
        self.engine.chat(messages, params, parts.append, cancel)
        return "".join(parts)
