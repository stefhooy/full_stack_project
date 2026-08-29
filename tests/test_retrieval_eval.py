"""Gates the RAG retrieval eval in CI: a real regression test, not just a
reportable script, since retrieve() only calls the local embedding model
(free, deterministic, no LLM) -- see src/evals/retrieval_eval.py's
docstring for why this eval specifically can run in CI when the rest of
the eval harness can't.

The bar (1.0, i.e. every golden question gets every expected chunk back)
is not a guess -- it's the real, measured recall@8 at production's actual
RAG_TOP_K, confirmed deterministic across repeated runs before being
locked in here. A future corpus edit, embedding-model change, or
schema_index.py change that makes retrieval worse will fail this test
instead of silently shipping.
"""

from __future__ import annotations

from src.config import settings
from src.evals.retrieval_eval import evaluate_retrieval


def test_retrieval_recall_at_production_top_k_stays_at_the_measured_baseline():
    report = evaluate_retrieval(top_k=settings.rag_top_k)
    failures = [
        f"{r.golden.id!r} (recall={r.recall:.2f}, missed={sorted(r.missed)})"
        for r in report.results
        if r.recall < 1.0
    ]
    assert not failures, (
        f"retrieval recall@{report.top_k} dropped below the measured 1.0 baseline "
        f"for: {failures}"
    )
    assert report.overall_recall == 1.0
