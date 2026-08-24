"""LLM-as-judge: a second, qualitative signal alongside the deterministic
checks in checks.py.

The deterministic checks catch specific, known failure shapes (wrong
route, mislabeled group, fabricated data). The judge is for everything
else those checks don't cover — is the answer actually clear, does it
correctly caveat a data limitation, does it state the right conclusion in
words even when the underlying numbers were checked separately. Given
reference facts (computed the same way as the deterministic checks: live
from the DB, not hardcoded) so it's judging factual consistency, not
grading against its own guess at the right answer.

Same structured-output pattern as src/agent/router.py, for the same
reason: a judge that can reply with anything but a valid score isn't
usable as a regression signal.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.agent.llm_provider import get_llm

JUDGE_SYSTEM_PROMPT = """You are grading an AI data analyst's answer to a question about a \
video game market dataset. You are given the question, reference facts (ground truth, \
computed directly from the database), and the AI's answer.

Judge whether the AI's answer is FACTUALLY CONSISTENT with the reference facts — not whether \
you would have phrased it the same way. Minor wording differences, extra context, or a \
different level of detail are fine. Wrong numbers, wrong conclusions, or claims not \
supported by the reference facts are not.

Score 1-5:
  5 = fully correct and consistent with the reference facts
  3 = partially correct, or correct but missing something the reference facts call out
  1 = contradicts the reference facts or fabricates information
"""


class JudgeVerdict(BaseModel):
    correct: bool = Field(description="True if the answer is factually consistent with the reference facts.")
    score: int = Field(ge=1, le=5, description="1 = wrong/fabricated, 5 = fully correct.")
    rationale: str = Field(description="One sentence explaining the score.")


def judge_answer(question: str, answer: str, reference_facts: str) -> JudgeVerdict:
    judge_llm = get_llm().with_structured_output(JudgeVerdict)
    prompt = (
        f"Question: {question}\n\n"
        f"Reference facts (ground truth):\n{reference_facts}\n\n"
        f"AI's answer:\n{answer}"
    )
    return judge_llm.invoke([SystemMessage(content=JUDGE_SYSTEM_PROMPT), HumanMessage(content=prompt)])
