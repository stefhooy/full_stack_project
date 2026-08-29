"""The RAG retrieval eval: does SchemaIndex.retrieve() actually surface the
schema chunks a question needs, not just whether the final answer came out
right.

Unlike run_evals.py's golden-question harness, this never calls an LLM —
retrieve() only runs the local embedding model, so this eval is free and
fast enough to run in CI on every push (see tests/test_retrieval_eval.py),
unlike the rest of the eval harness (real Groq calls, cost/rate-limit
gated, manual-only).

Metric is recall@k: of the chunks a question is hand-labeled as needing
(retrieval_golden.py — deliberately excluding always_include chunks, which
are returned regardless of ranking and so prove nothing about it), what
fraction actually came back in the top-k. Averaged across the golden set
for one overall number.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.agent.rag.schema_index import get_schema_index
from src.evals.retrieval_golden import RETRIEVAL_GOLDEN, RetrievalGoldenQuestion


@dataclass
class RetrievalResult:
    golden: RetrievalGoldenQuestion
    retrieved_ids: frozenset[str]
    recall: float
    missed: frozenset[str]


@dataclass
class RetrievalEvalReport:
    top_k: int
    results: list[RetrievalResult]
    overall_recall: float


def evaluate_retrieval(top_k: int) -> RetrievalEvalReport:
    index = get_schema_index()
    results = []
    for golden in RETRIEVAL_GOLDEN:
        retrieved = index.retrieve(golden.question, top_k=top_k)
        retrieved_ids = frozenset(c.id for c in retrieved)
        hits = golden.expected_chunk_ids & retrieved_ids
        recall = len(hits) / len(golden.expected_chunk_ids) if golden.expected_chunk_ids else 1.0
        missed = golden.expected_chunk_ids - retrieved_ids
        results.append(RetrievalResult(golden, retrieved_ids, recall, missed))

    overall = sum(r.recall for r in results) / len(results) if results else 1.0
    return RetrievalEvalReport(top_k=top_k, results=results, overall_recall=overall)


def print_report(report: RetrievalEvalReport) -> None:
    print(f"\nRAG retrieval eval (recall@{report.top_k}, {len(report.results)} questions)")
    print("-" * 100)
    for r in report.results:
        status = "PASS" if r.recall == 1.0 else "PARTIAL" if r.recall > 0 else "FAIL"
        print(f"{r.golden.id:24s} {status:8s} recall={r.recall:.2f}  {r.golden.question}")
        if r.missed:
            print(f"{'':24s} {'':8s} missed: {sorted(r.missed)}")
    print("-" * 100)
    print(f"Overall recall@{report.top_k}: {report.overall_recall:.3f}\n")


if __name__ == "__main__":
    import argparse

    from src.config import settings

    parser = argparse.ArgumentParser(description="Run the RAG retrieval eval.")
    parser.add_argument("--top-k", type=int, default=settings.rag_top_k)
    args = parser.parse_args()

    print_report(evaluate_retrieval(top_k=args.top_k))
