"""Phase 5 — Embed all chunks once with the pinned model, build a FAISS index.

Pinned model: BAAI/bge-base-en-v1.5

Per the model card:
  - Use a query-side instruction prefix for retrieval:
      "Represent this sentence for searching relevant passages: " + query
  - Do NOT prefix documents (passages) when indexing.
  - Sentences are encoded with mean pooling + L2 normalization; cosine becomes
    inner product on the normalized vectors.

We pin the HuggingFace revision (commit SHA) on first download and record it.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np

MODEL_ID = "BAAI/bge-base-en-v1.5"
# Pinned at the current HF commit of the model repo. Recorded once; never
# change without rebuilding the entire datastore.
MODEL_REVISION = "a5beb1e3e68b9ab74eb54cfd186867f64f240e1a"

QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def encode_passages(model, texts: list[str], batch_size: int = 32) -> np.ndarray:
    return model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )


def encode_queries(model, queries: list[str]) -> np.ndarray:
    prefixed = [QUERY_INSTRUCTION + q for q in queries]
    return model.encode(
        prefixed,
        batch_size=32,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )


def load_chunks(jsonl_path: Path) -> list[dict]:
    chunks: list[dict] = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                chunks.append(json.loads(line))
    return chunks


def build_index(chunks_jsonl: Path, out_dir: Path) -> dict:
    from sentence_transformers import SentenceTransformer
    import faiss

    out_dir.mkdir(parents=True, exist_ok=True)
    chunks = load_chunks(chunks_jsonl)
    texts = [c["text"] for c in chunks]
    ids = [c["chunk_id"] for c in chunks]

    print(f"Loading model {MODEL_ID}@{MODEL_REVISION}")
    model = SentenceTransformer(MODEL_ID, revision=MODEL_REVISION)

    print(f"Encoding {len(texts)} chunks...")
    vecs = encode_passages(model, texts).astype("float32")

    dim = vecs.shape[1]
    # Inner-product on L2-normalized vectors == cosine
    index = faiss.IndexFlatIP(dim)
    index.add(vecs)

    index_path = out_dir / "lean_docs.faiss"
    ids_path = out_dir / "lean_docs.ids.json"
    meta_path = out_dir / "lean_docs.meta.json"

    faiss.write_index(index, str(index_path))
    with ids_path.open("w", encoding="utf-8") as f:
        json.dump(ids, f)

    index_sha256 = hash_file(index_path)
    meta = {
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "query_instruction": QUERY_INSTRUCTION,
        "dim": dim,
        "n_vectors": int(index.ntotal),
        "metric": "inner_product_on_l2_normalized (== cosine)",
        "index_path": index_path.name,
        "ids_path": ids_path.name,
        "index_sha256": index_sha256,
    }
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print(json.dumps(meta, indent=2))
    return meta


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    build_index(args.chunks, args.out)
