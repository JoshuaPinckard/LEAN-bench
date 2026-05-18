"""Write the canonical DATASTORE_SPEC.json after the full pipeline completes.

Captures every input needed to reproduce the index byte-for-byte:
  source commit + .NET SDK version + embedding model revision -> hashed index
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from .embed_chunks import MODEL_ID, MODEL_REVISION


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--lean-src", required=True, type=Path)
    ap.add_argument("--chunks", required=True, type=Path)
    ap.add_argument("--index-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=args.lean_src
    ).decode().strip()

    sdk_version = "10.0.300"  # pinned in lean_src/global.json
    # belt-and-suspenders: read it back from global.json
    gj = args.lean_src / "global.json"
    if gj.exists():
        sdk_version = json.loads(gj.read_text())["sdk"]["version"]

    # chunk count
    n_chunks = sum(1 for _ in args.chunks.open("r", encoding="utf-8") if _.strip())

    # completeness check result
    from .completeness_check import find_setholdings_overloads, load_chunks
    chunks = load_chunks(args.chunks)
    sh = find_setholdings_overloads(chunks)

    # index hash
    index_path = args.index_dir / "lean_docs.faiss"
    index_sha = sha256_file(index_path)
    meta_path = args.index_dir / "lean_docs.meta.json"
    meta = json.loads(meta_path.read_text())

    spec = {
        "datastore_version": "1.0.0",
        "lean_repo": "https://github.com/QuantConnect/Lean",
        "lean_commit": commit,
        "dotnet_sdk_version": sdk_version,
        "build_target_framework": "net10.0",
        "build_configuration": "Release",
        "phase2_branch": "Roslyn (build passed; QuantConnect.Algorithm.xml, QuantConnect.Indicators.xml, QuantConnect.Common.xml all produced)",
        "documented_assemblies": 14,
        "chunk_count": n_chunks,
        "max_chars_guard": 8000,
        "max_chars_note": "defensive only",
        "completeness_mode": "(b) documented members only — Roslyn XML covers exactly the members with /// comments, matching the published QuantConnect API reference that LEAN developers consult",
        "setholdings_overloads_present": len(sh),
        "embedding_model_id": MODEL_ID,
        "embedding_model_revision": MODEL_REVISION,
        "embedding_dim": meta["dim"],
        "embedding_metric": meta["metric"],
        "query_instruction_prefix": meta["query_instruction"],
        "faiss_index_path": str(index_path.relative_to(args.index_dir.parent)),
        "faiss_index_sha256": index_sha,
        "faiss_vectors": meta["n_vectors"],
        "retrieval_top_k": 5,
        "retrieval_top_k_note": "fixed; not tuned",
        "canonical_artifact": f"commit={commit} | sdk={sdk_version} | model={MODEL_ID}@{MODEL_REVISION} | index_sha256={index_sha}",
    }

    args.out.write_text(json.dumps(spec, indent=2))
    print(json.dumps(spec, indent=2))


if __name__ == "__main__":
    main()
