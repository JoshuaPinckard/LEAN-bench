"""LEAN RAG datastore — frozen retrieval over QuantConnect LEAN source docs.

Agent-facing import surface:

    from lean_rag import retrieve
    chunks = retrieve("set holdings to a percentage of portfolio")

`retrieve(query: str) -> list[str]` returns the top-k=5 raw chunk texts for
`query` and appends one record per call (query + returned chunk IDs) to
`lean_rag/logs/retrieval.log.jsonl`.

The datastore (FAISS index + chunks) is a frozen canonical artifact — see
DATASTORE_SPEC.json for the integrity hash, embedding model, and source
commit. Do not rebuild it without a deliberate decision: replacing a verified
canonical artifact is a methodology change, not a side effect.
"""

from lean_rag.datastore.retrieve import retrieve

__all__ = ["retrieve"]
