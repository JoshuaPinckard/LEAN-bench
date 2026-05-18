"""Phase 7 — Retrieval tool for the agentic harness.

Single function. One string argument. Returns top-k=5 raw chunk texts (fixed).
Every call is logged: query + returned chunk IDs.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np

from .embed_chunks import MODEL_ID, MODEL_REVISION, QUERY_INSTRUCTION

TOP_K = 5  # fixed by spec, not tuned.

_DEFAULT_INDEX_DIR = Path(__file__).resolve().parent.parent / "index"
_DEFAULT_CHUNKS = Path(__file__).resolve().parent.parent / "chunks" / "chunks.jsonl"
_DEFAULT_LOG = Path(__file__).resolve().parent.parent / "logs" / "retrieval.log.jsonl"

_state_lock = threading.Lock()
_state: dict = {}


def _ensure_loaded(index_dir: Path, chunks_path: Path) -> dict:
    global _state
    if _state.get("loaded"):
        return _state
    with _state_lock:
        if _state.get("loaded"):
            return _state
        from sentence_transformers import SentenceTransformer
        import faiss

        meta_path = index_dir / "lean_docs.meta.json"
        ids_path = index_dir / "lean_docs.ids.json"
        index_path = index_dir / "lean_docs.faiss"

        with meta_path.open("r", encoding="utf-8") as f:
            meta = json.load(f)
        with ids_path.open("r", encoding="utf-8") as f:
            ids = json.load(f)
        index = faiss.read_index(str(index_path))

        # Load chunks once into id->record
        chunks_by_id: dict[str, dict] = {}
        with chunks_path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    chunks_by_id[rec["chunk_id"]] = rec

        model = SentenceTransformer(meta["model_id"], revision=meta["model_revision"])

        _state.update(
            {
                "loaded": True,
                "meta": meta,
                "ids": ids,
                "index": index,
                "chunks_by_id": chunks_by_id,
                "model": model,
            }
        )
        return _state


def _log(query: str, returned_ids: list[str], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": time.time(),
        "query": query,
        "returned_ids": returned_ids,
        "top_k": TOP_K,
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def retrieve(
    query: str,
    index_dir: Optional[Path] = None,
    chunks_path: Optional[Path] = None,
    log_path: Optional[Path] = None,
) -> list[str]:
    """Top-k=5 raw chunk texts for `query`. Logs query + returned chunk IDs."""
    index_dir = Path(index_dir) if index_dir else _DEFAULT_INDEX_DIR
    chunks_path = Path(chunks_path) if chunks_path else _DEFAULT_CHUNKS
    log_path = Path(log_path) if log_path else _DEFAULT_LOG

    s = _ensure_loaded(index_dir, chunks_path)
    prefixed = QUERY_INSTRUCTION + query
    vec = s["model"].encode(
        [prefixed], convert_to_numpy=True, normalize_embeddings=True
    ).astype("float32")
    scores, idxs = s["index"].search(vec, TOP_K)
    idxs = idxs[0].tolist()
    returned_ids = [s["ids"][i] for i in idxs if i >= 0]
    _log(query, returned_ids, log_path)
    texts = [s["chunks_by_id"][cid]["text"] for cid in returned_ids]
    return texts


def retrieve_with_ids(
    query: str,
    index_dir: Optional[Path] = None,
    chunks_path: Optional[Path] = None,
    log_path: Optional[Path] = None,
) -> list[tuple[str, str, float]]:
    """Diagnostic variant: (chunk_id, text, score). Not for the harness."""
    index_dir = Path(index_dir) if index_dir else _DEFAULT_INDEX_DIR
    chunks_path = Path(chunks_path) if chunks_path else _DEFAULT_CHUNKS
    log_path = Path(log_path) if log_path else _DEFAULT_LOG

    s = _ensure_loaded(index_dir, chunks_path)
    prefixed = QUERY_INSTRUCTION + query
    vec = s["model"].encode(
        [prefixed], convert_to_numpy=True, normalize_embeddings=True
    ).astype("float32")
    scores, idxs = s["index"].search(vec, TOP_K)
    out = []
    for i, sc in zip(idxs[0].tolist(), scores[0].tolist()):
        if i < 0:
            continue
        cid = s["ids"][i]
        out.append((cid, s["chunks_by_id"][cid]["text"], float(sc)))
    _log(query, [cid for cid, _, _ in out], log_path)
    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    args = ap.parse_args()
    for cid, text, score in retrieve_with_ids(args.query):
        print(f"\n=== {score:.4f}  {cid} ===\n{text}")
