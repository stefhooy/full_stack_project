"""Guards the RAG schema corpus's shape, not just its content -- a real
production incident (DOCEXP.md's Slice 50) traced to one chunk growing to
1,465 characters across three separate, individually-reasonable bug
fixes (Slices 40, 42, 44), which then blew up SchemaIndex's batch-embed
call's memory cost by ~450MB. Fixing that call site (Slice 50/51) removes
today's specific trigger, but nothing stopped the next well-intentioned
"add a bit more guidance" edit from quietly growing another chunk the
same way. This test is that guardrail: it fails loudly, in CI, the
moment a chunk crosses the ceiling, instead of only being noticed the
next time someone happens to run a memory profile.
"""

from __future__ import annotations

from src.agent.rag.schema_corpus import SCHEMA_CHUNKS

# Set with real headroom above the corpus's current legitimate long
# chunks (478 chars as of this writing) but well below the 1,465
# characters that actually caused Slice 50's incident -- tight enough to
# catch a real regression, loose enough not to fight normal, reasonably
# detailed guidance.
MAX_CHUNK_LENGTH = 600


def test_no_chunk_exceeds_the_length_ceiling():
    oversized = [(c.id, len(c.text)) for c in SCHEMA_CHUNKS if len(c.text) > MAX_CHUNK_LENGTH]
    assert not oversized, (
        f"chunk(s) over the {MAX_CHUNK_LENGTH}-character ceiling: {oversized} -- "
        "split into smaller, focused chunks instead of growing one further "
        "(see DOCEXP.md's Slice 50 entry for why this specific ceiling exists: "
        "a single long chunk this size, batch-embedded, was directly responsible "
        "for a real Render OOM incident)."
    )


def test_every_chunk_id_is_unique():
    ids = [c.id for c in SCHEMA_CHUNKS]
    duplicates = {i for i in ids if ids.count(i) > 1}
    assert not duplicates, f"duplicate schema chunk id(s): {duplicates}"
