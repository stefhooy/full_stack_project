"""Local, free, instant memory-usage diagnostic for the RAG/embedding
pipeline -- run this before ever redeploying to check whether a change
regressed the app's memory footprint.

Why this exists: a real Render production incident (Slice 49) traced to
`SchemaIndex` batch-embedding the whole schema corpus in a single call,
spiking memory by ~450MB and exceeding Render's free-tier 512MB hard
ceiling -- confirmed directly via Render's own dashboard ("Ran out of
memory (used over 512MB) while running your code"). Diagnosing this
against the real deployment meant a commit -> push -> redeploy -> ask a
real question -> read Render's logs cycle, each round trip costing
several real minutes and, once a real question got asked, real Groq
quota. Once the actual mechanism was suspected, isolating it precisely
took three quick local runs of scripts like this one -- no deploy, no
LLM call, no cost. This module is that approach made permanent and
reusable, instead of a one-off throwaway script.

Mirrors production's real import shape (`import src.agent.graph` pulls in
the exact same LangGraph/LangChain/DuckDB/SciPy/Groq-client stack the
live app loads at module-import time) so the baseline before the
embedding steps is realistic, not an isolated best case.

Usage:
    uv run python -m src.diagnostics.memory_probe
"""

from __future__ import annotations

import sys

import psutil

_proc = psutil.Process()

# The real, confirmed hard ceiling on Render's free tier (see DOCEXP.md's
# Slice 49 entry -- this exact number came from Render's own dashboard,
# not a guess). Kept here so this script's pass/fail check is measured
# against the actual constraint being protected against, not an arbitrary
# threshold.
RENDER_FREE_TIER_LIMIT_MB = 512

# How much building the schema index over the real corpus should ever
# realistically cost -- measured at ~11.5MB for embedding the same real
# corpus one chunk at a time (see DOCEXP.md's Slice 49 entry); 50MB is
# real headroom above that without being so loose it'd miss a real
# regression back toward batch-embedding's ~445MB.
SCHEMA_INDEX_BUILD_BUDGET_MB = 50


def _mb() -> float:
    return _proc.memory_info().rss / (1024 * 1024)


def _checkpoint(label: str) -> float:
    peak = _mb()
    print(f"MEMORY [{label}]: RSS = {peak:.1f} MB")
    return peak


def main() -> int:
    _checkpoint("process start")

    import src.agent.graph  # noqa: F401 -- side effect: pulls in the exact same
    # import graph production loads at module-import time (LangGraph,
    # LangChain, DuckDB, SciPy, the Groq client), so the baseline below
    # reflects production's real starting point, not an isolated best case.

    _checkpoint("after importing the full agent stack (matches production's module-load baseline)")

    from src.agent.rag.embeddings import get_embedder
    from src.agent.rag.schema_corpus import SCHEMA_CHUNKS
    from src.agent.rag.schema_index import get_schema_index

    get_embedder()
    after_embedder = _checkpoint("after get_embedder() (loads the ONNX model into memory)")

    get_embedder().embed_query("a representative test question")
    _checkpoint("after ONE query embed (the semantic cache's real per-request cost)")

    lens = sorted(len(c.text) for c in SCHEMA_CHUNKS)
    print(
        f"(schema corpus: {len(lens)} chunks, {lens[0]}-{lens[-1]} chars, "
        f"median {lens[len(lens) // 2]})"
    )

    get_schema_index()  # first call builds the index -- exercises whatever
    # the REAL current implementation does (one at a time vs. one batch
    # call), not a reimplementation of either -- so this stays a true
    # regression guard against the actual code, not a simulation of it.
    after_index = _checkpoint("after get_schema_index() (builds the index over the real corpus)")

    index_build_cost = after_index - after_embedder
    print()
    print(f"Schema index build cost: {index_build_cost:.1f} MB")
    print(
        f"Peak so far: {after_index:.1f} MB / "
        f"{RENDER_FREE_TIER_LIMIT_MB} MB Render free-tier limit"
    )

    if index_build_cost > SCHEMA_INDEX_BUILD_BUDGET_MB:
        print(
            f"\nFAIL: building the schema index cost {index_build_cost:.1f} MB, "
            f"over the {SCHEMA_INDEX_BUILD_BUDGET_MB} MB budget. This is exactly "
            "the shape of the real Slice 49 incident (batch-embedding a text "
            "corpus with a long outlier chunk) -- check schema_index.py hasn't "
            "reverted to a single batch embed_texts() call over the whole corpus."
        )
        return 1

    print(
        f"\nPASS: schema index build cost is within the "
        f"{SCHEMA_INDEX_BUILD_BUDGET_MB} MB budget."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
