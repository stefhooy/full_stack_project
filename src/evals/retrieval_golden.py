"""Hand-labeled golden set for the RAG retrieval eval: for each question,
the specific schema chunks retrieval *should* surface.

Deliberately excludes chunks marked `always_include=True` in
src/agent/rag/schema_corpus.py (table:games, column:name, column:genre,
table:player_counts) from every expected set — those bypass ranking
entirely and are returned regardless of the question, so testing for them
would just prove SchemaIndex.retrieve() didn't change, not that the
ranking algorithm did its job. This eval is specifically about the ~30
chunks that have to earn their spot by actually being relevant.

Each question is written the way a real user would ask it (matching the
style of the frontend's example questions and golden_questions.py), not
as a keyword-stuffed search query, since that's what retrieval actually
has to handle in production.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalGoldenQuestion:
    id: str
    question: str
    expected_chunk_ids: frozenset[str]


RETRIEVAL_GOLDEN: list[RetrievalGoldenQuestion] = [
    RetrievalGoldenQuestion(
        id="playtime",
        question="How many hours have people played Portal 2 in total?",
        expected_chunk_ids=frozenset(
            {
                "column:average_playtime_forever_min",
                "metric:playtime_units",
                "metric:playtime_often_zero",
            }
        ),
    ),
    RetrievalGoldenQuestion(
        id="recent_playtime",
        question="What's the average playtime over the last two weeks for this game?",
        expected_chunk_ids=frozenset(
            {"column:average_playtime_2weeks_min", "metric:playtime_units"}
        ),
    ),
    RetrievalGoldenQuestion(
        id="discount",
        question="Which games have the biggest discount off their original price right now?",
        expected_chunk_ids=frozenset(
            {"column:price_usd", "column:initial_price_usd", "column:discount_pct"}
        ),
    ),
    RetrievalGoldenQuestion(
        id="owners",
        question="How many owners does Palworld have?",
        expected_chunk_ids=frozenset(
            {"column:owners_low", "column:owners_high", "metric:owners_midpoint"}
        ),
    ),
    RetrievalGoldenQuestion(
        id="review_score_percent",
        question="What's the highest rated game by review score, as a percentage?",
        expected_chunk_ids=frozenset({"column:review_score", "metric:review_score_is_fraction"}),
    ),
    RetrievalGoldenQuestion(
        id="dev_publisher",
        question="Which developer or publisher has released the most games in the catalog?",
        expected_chunk_ids=frozenset({"column:developer", "column:publisher"}),
    ),
    RetrievalGoldenQuestion(
        id="compare_two_groups",
        question=(
            "Compare the average price of Action games to free-to-play games in one query."
        ),
        expected_chunk_ids=frozenset({"metric:no_union", "column:price_usd"}),
    ),
    RetrievalGoldenQuestion(
        id="languages",
        question="Does this game support French or German?",
        expected_chunk_ids=frozenset({"column:languages"}),
    ),
    RetrievalGoldenQuestion(
        id="release_date",
        question="When was this game released?",
        expected_chunk_ids=frozenset({"column:release_date", "column:release_date_raw"}),
    ),
    RetrievalGoldenQuestion(
        id="metacritic",
        question="What's this game's Metacritic score?",
        expected_chunk_ids=frozenset({"column:metacritic_score"}),
    ),
    RetrievalGoldenQuestion(
        id="platforms",
        question="Does this game run on Mac or Linux?",
        expected_chunk_ids=frozenset({"column:platforms"}),
    ),
    RetrievalGoldenQuestion(
        id="categories",
        question="Does this game support co-op multiplayer?",
        expected_chunk_ids=frozenset({"column:categories"}),
    ),
    RetrievalGoldenQuestion(
        id="live_player_count",
        question="How many people are playing this game right now, live?",
        expected_chunk_ids=frozenset(
            {
                "column:player_counts.player_count",
                "metric:peak_ccu_vs_player_counts",
                "metric:player_counts_is_a_join",
            }
        ),
    ),
    RetrievalGoldenQuestion(
        id="player_count_trend",
        question="How has this game's player count changed over time?",
        expected_chunk_ids=frozenset(
            {"column:player_counts.polled_at", "metric:player_counts_is_a_join"}
        ),
    ),
    RetrievalGoldenQuestion(
        id="reviews_breakdown",
        question="How many positive versus negative reviews does this game have?",
        expected_chunk_ids=frozenset({"column:positive_reviews", "column:negative_reviews"}),
    ),
]
