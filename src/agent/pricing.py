"""Shared Groq pricing, used identically by the live agent (graph.py, for
real /ask requests) and the eval harness (src/evals/run_evals.py, for
gathering the numbers published in README.md's "Measured results"). One
source of pricing truth so a real production request and an eval run
compute cost the same way, not two independently-maintained copies that
could silently drift apart.

$/million tokens, Groq's on-demand tier, verified live against Groq's own
pricing (not assumed from training data) on 2026-08-29 -- see DOCEXP.md's
Slice 24 entry. Keyed by model name since usage is reported per-model, and
a future MODEL_PROVIDER/GROQ_MODEL change would otherwise silently price
against the wrong rate.

Deliberately doesn't account for Groq's cheaper cached-input rate (real
input tokens sometimes get served from Groq's own prompt cache at a
discount) -- using the plain non-cached rate for every input token is a
simpler number to state and a conservative one: it can only overstate
real cost, never understate it.
"""

from __future__ import annotations

GROQ_PRICING_USD_PER_MILLION_TOKENS = {
    "openai/gpt-oss-120b": {"input": 0.15, "output": 0.60},
}


def estimate_cost_usd(usage_by_model: dict) -> float | None:
    """None if any model in usage_by_model has no known pricing -- silently
    returning a partial (and therefore wrong-looking-precise) number would
    be worse than admitting the estimate isn't possible."""
    total = 0.0
    known_pricing = True
    for model, usage in usage_by_model.items():
        pricing = GROQ_PRICING_USD_PER_MILLION_TOKENS.get(model)
        if pricing is None:
            known_pricing = False
            continue
        total += usage.get("input_tokens", 0) * pricing["input"] / 1_000_000
        total += usage.get("output_tokens", 0) * pricing["output"] / 1_000_000
    return total if known_pricing else None
