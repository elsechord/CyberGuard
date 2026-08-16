"""Versioned, deterministic security knowledge retrieval for CyberGuard."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


class KnowledgeStore:
    """Search only curated documents; never present them as incident evidence."""

    def __init__(self) -> None:
        # The container uses /app while local tests use the repository root.
        default = Path("/app/knowledge")
        self.data_dir = Path(os.getenv("CYBERGUARD_KNOWLEDGE_DIR", default))

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        terms = set(re.findall(r"[a-z0-9_.-]+|[\u4e00-\u9fff]{2,}", query.lower()))
        if not terms or not self.data_dir.exists():
            return []
        hits: list[tuple[int, dict[str, Any]]] = []
        for path in sorted(self.data_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            documents = payload if isinstance(payload, list) else [payload]
            for document in documents:
                if not isinstance(document, dict):
                    continue
                text = " ".join(str(document.get(key, "")) for key in ("title", "tags", "content"))
                normalized = text.lower()
                score = sum(term in normalized for term in terms)
                if score:
                    canonical = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    hits.append((score, {
                        "document_id": document["document_id"],
                        "version": document["version"],
                        "title": document["title"],
                        "source": document["source"],
                        "content": document["content"],
                        "content_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                        "score": score,
                        "classification": document.get("classification", "internal"),
                        "disclaimer": "这是可复用知识，不是当前事件的事实证据。",
                    }))
        return [item for _, item in sorted(hits, key=lambda item: (-item[0], item[1]["document_id"]))[:limit]]


knowledge_store = KnowledgeStore()
