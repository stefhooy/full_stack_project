# DOCEXP — Engineering Log

A running lab notebook: decisions and why, what broke, what surprised me,
open questions. Written as I go, not after the fact.

---

## Slice 1 — Repo, ingestion, guarded DB, minimal self-correcting SQL agent

**Date:** 2026-08-22

### Repo structure

```
src/
  config.py          # one typed Settings object, everything reads from here
  ingestion/          # SteamSpy client + the ingest script
  db/                 # schema + the read-only guarded connection (the safety boundary)
  agent/               # LangGraph graph, prompts, provider seam
  tools/               # run_sql today; stats/forecast/viz tools land in Slice 4
  api/                 # FastAPI — thin, translates HTTP <-> agent
data/
  raw/                 # cached SteamSpy responses (gitignored)
  db/                  # the DuckDB file (gitignored)
```

Why split this way instead of one file: each top-level package maps to one
layer of the final architecture (ingestion, storage, reasoning, tools,
transport), so slices 2-8 mostly mean *adding* files to these packages
rather than restructuring. `api/` importing from `agent/` but not vice versa
is deliberate — the agent has to run standalone (scriptable, testable,
traceable) without ever knowing FastAPI exists. That's also what keeps the
deployment-target decision (see Open Questions) from leaking into the
agent code.

### The safety boundary: SELECT-only enforcement

This is the one part of the system I did not want to get subtly wrong, so
I spent the most care here. Two independent layers:

1. DuckDB connection opened with `read_only=True` — the engine itself
   refuses writes, regardless of what Python code does.
2. `src/db/connection.py::validate_select_only()` parses every query with
   **sqlglot** (a real SQL parser) before it reaches DuckDB at all, and
   rejects anything that isn't a single `SELECT`/CTE statement touching
   only the `games` table.

Layer 2 exists even though layer 1 already blocks writes, because
`read_only=True` doesn't stop everything that could be a problem — `ATTACH`,
`COPY ... TO`, or stacked statements (`SELECT ...; DROP TABLE ...;`) aren't
writes to *our* table but aren't things an LLM-generated query should ever
be allowed to try either. I initially considered regex/keyword blacklisting
(reject if the string contains "DROP", "INSERT", etc.) and deliberately
rejected that approach — it's trivially defeated by comments, string
literals, or case tricks, and it can't tell a legitimate `WITH deleted AS
(...)` CTE from an actual `DELETE`. A real parser can.

Tested the guard directly against a battery of attacks before ever wiring
it to an LLM (`DROP TABLE`, stacked `SELECT; DROP`, `INSERT`, cross-table
`UNION`, `ATTACH 'evil.db'`, unknown table names) — all correctly rejected;
legitimate `SELECT` and CTE queries correctly passed and got their `LIMIT`
clause capped. Row capping is done by editing the parsed AST (add or shrink
a `LIMIT` node) rather than string-concatenating `" LIMIT N"` onto
arbitrary SQL, which would break on queries that already end in a comment
or a trailing semicolon.

**Surprising finding:** the parser-based approach means any query that
isn't literally an `exp.Select` node gets rejected — including legitimate
`UNION` queries, since sqlglot parses those as `exp.Union`, not
`exp.Select`. Not a problem for Slice 1 (single-table catalog, no reason
to union), but worth knowing: if a future slice needs UNION (e.g. comparing
two time ranges), `validate_select_only` needs an explicit allowance for it
rather than assuming "not Select => reject" is always right.

### Agent: hand-written LangGraph loop, not `create_react_agent`

The instruction I'm building to is "every node must be explainable in an
interview," so I wrote the tool-calling loop by hand instead of using
LangGraph's prebuilt agent constructor. It's two nodes:

- `agent`: calls the LLM (with `run_sql` bound as a tool) on the message
  history so far.
- `execute_tools`: runs each tool call through the guarded DB layer,
  turns a DuckDB or validation error into a `ToolMessage` the model reads
  on its next turn, and records the last *successful* query + rows.

The retry cap is enforced structurally, not by asking the model nicely to
stop: once `attempts >= SQL_MAX_RETRIES`, `agent_node` stops calling
`.bind_tools([run_sql])` on that turn at all, so the LLM has no tool to
call and is forced to produce a plain-text final answer. This guarantees
the loop terminates without needing a hard step ceiling as a backstop
(LangGraph's default recursion limit is still there as a last resort, but
it should never be hit in normal operation).

`schema-in-prompt` today is a plain string built by
`src/agent/prompts.py::build_system_prompt()`. It takes an optional
`schema_text` override specifically so Slice 2 (RAG retrieval) can swap in
"only the columns this question needs" without changing the function's
signature or any call site outside of where the retrieval step gets added.

### Model provider seam

`src/agent/llm_provider.py::get_llm()` is the only place allowed to branch
on `MODEL_PROVIDER`. Everything else calls `get_llm()` and gets back a
LangChain `BaseChatModel` — the graph code has no idea whether it's Groq,
Ollama, or (later) Gemini. The Gemini branch currently raises
`NotImplementedError` on purpose: didn't want to add the
`langchain-google-genai` dependency before a slice actually needs it, but
the seam (the `if provider == "gemini":` branch) is there so adding it
later is additive, not a refactor.

### SteamSpy API — what I learned poking at it directly

Two endpoints matter for this slice:
- `request=all&page=0`: bulk listing, ~1000 games per page, already sorted
  by owners descending. Cheap — no rate limit concern, one request gets us
  the whole candidate pool.
- `request=appdetails&appid=X`: per-game detail. This is the *only* place
  `genre`, `languages`, and `tags` show up — the bulk `all` endpoint does
  not include them. SteamSpy's own guidance asks for ~1 request/second on
  this endpoint, which is why ingesting 200 games takes ~3-4 minutes.

Both raw responses get cached to `data/raw/*.json` keyed by request. That's
what makes `ingest.py` idempotent and fast to re-run: a second run replays
cache hits for `appdetails` instead of re-fetching (and re-waiting a full
second per game), and rows are UPSERTed on `appid` via
`ON CONFLICT (appid) DO UPDATE`, so no duplicates either way. Verified this
directly: ran ingestion twice at `--count 20`, row count stayed at 20 both
times, second run finished near-instantly.

### Surprise: Avast TLS interception broke every outbound HTTPS request

First ingestion run failed immediately with
`SSLCertVerificationError: unable to get local issuer certificate` on a
plain `requests.get()` to steamspy.com — before any of our code, just the
TLS handshake. Root cause: this machine's Avast antivirus does HTTPS
web-shield interception, re-signing traffic with its own locally-installed
root CA. Windows trusts that CA (Avast installed it into the system store);
Python's `requests`/`urllib3` don't use the Windows trust store by
default — they validate against `certifi`'s bundled CA list, which
obviously doesn't include a locally-generated antivirus root cert. curl
(used to explore the API earlier) worked fine because it uses the OS trust
store directly on Windows, which is what pointed at the real cause.

Fixed properly rather than papering over it: added the `truststore`
package and called `truststore.inject_into_ssl()` once at import time in
`steamspy_client.py`. This makes the stdlib `ssl` module validate against
the OS trust store instead of `certifi`, which is correct on any machine
(not just this one) and doesn't disable verification (`verify=False` was
the tempting shortcut and deliberately not what I did — that would silently
accept a real MITM too, not just Avast's).

### What worked without any fuss

- DuckDB's `ON CONFLICT ... DO UPDATE` — worked first try, no schema
  migration ceremony needed for an idempotent upsert.
- `pydantic-settings` reading `.env` — one `Settings` object, and
  `load_dotenv()` at the top of `config.py` also populates `os.environ`
  directly, which turned out to matter for LangSmith: its tracer reads
  `LANGSMITH_*` straight from `os.environ`, not from anything our code
  passes it, so tracing "just works" once the `.env` values are set — no
  extra wiring needed beyond making sure they land in the process
  environment before any LangChain code runs.

### Surprise: DuckDB's file lock means you can't ingest and serve at once

While the 200-game ingestion run was in progress (write connection open),
a read-only connection to the same file failed immediately:
`IO Error: Cannot open file ... The process cannot access the file because
it is being used by another process.` DuckDB allows multiple concurrent
*read-only* connections to a file, but a read-write connection takes an
exclusive OS-level lock — no reader can open the file at all until the
writer closes it. Not a bug, just a constraint to design around: the API
can't serve `/ask` while ingestion is running against the same file. Fine
for a local dev loop (ingestion finishes in a few minutes, then serve), but
worth remembering once ingestion is scheduled (Slice 7) — it'll need to
write to a fresh file and swap/rename rather than hold a long-lived write
connection open on the file the live API is reading from.

### Open questions

- **Deployment target** (flagged per the plan, not resolved now): backend
  is Python; free single-platform hosting on Vercel means either Vercel
  Python functions or a Vercel frontend + a separate free Python host
  (Render/Fly/Railway free tier). Revisit at Slice 6. Keeping `src/agent`
  and `src/db` free of any FastAPI import is what keeps both paths open.
- **UNION queries** — noted above; `validate_select_only` will need an
  explicit `exp.Union` allowance if a later slice needs to compare two
  result sets in one query, rather than assuming "anything that isn't
  `exp.Select` is unsafe."
- **Row cap vs. time cap** — Slice 1 only enforces a row cap. A query that
  scans a lot but returns few rows (unlikely on a ~200-row table, but will
  matter once `player_counts` time-series data shows up in Slice 7) has no
  cost guard yet.
- **Ingestion candidate pool** — top-N by owners (page 0 of `all`, already
  sorted) rather than a random or genre-diverse sample. Good enough for a
  first working slice; may want a more representative sample later so the
  agent isn't only ever talking about the same handful of mega-hits.

### End-to-end verification

Ran the full pipeline for real, not just unit-level: ingested 200 games,
started the FastAPI server, and hit `POST /ask` over HTTP (not just calling
`run_agent()` in-process) with all three README example questions.

Tested against **Ollama (llama3.1:8b, local)** rather than Groq, since I
don't have a Groq key in this environment — this doubled as a real test of
the provider seam (`MODEL_PROVIDER=ollama` in `.env`, zero code changes)
before ever running it against Groq.

- *"5 most-owned free-to-play games"* → correct on the first query. Model
  correctly used `(owners_low + owners_high) / 2` as instructed in the
  schema notes rather than picking one bound arbitrarily.
- *"Highest peak concurrent player count"* → correct on the first query,
  clean single-column SQL.
- *"Average price of Action games vs. free-to-play games"* → **failed
  outright on the first attempt.** The model wrote a `UNION` query to
  combine the two averages, which the guard rejects (see the UNION note
  above) — it burned all 3 retries retrying variants of the same rejected
  pattern and gave up, correctly responding "I was unable to complete the
  query" rather than fabricating numbers. That's the safety system doing
  exactly its job (fail honestly, don't hallucinate), but it meant a README
  example question flat-out didn't work. Fixed by adding one line to the
  system prompt telling the model to use conditional aggregation
  (`AVG(CASE WHEN ... THEN price_usd END)`) instead of `UNION` for
  comparing two groups. Retested: worked first try after the prompt change.

  Worth flagging honestly: the corrected query is *subtly wrong* — the
  `CASE WHEN price_usd = 0` free-to-play average ends up computed inside
  the outer `WHERE genre LIKE '%Action%'` filter, so it actually answers
  "average price of free *Action* games," not "average price of free-to-play
  games overall" (it happened to still print $0.00, which is correct by
  coincidence — any qualifying row has price 0). This is a small local
  model's reasoning limitation, not a guardrail/architecture gap — the SQL
  is syntactically valid and the guard has no way to (and shouldn't try to)
  catch semantic mistakes like this. It's exactly the kind of thing the
  Slice 5 eval harness needs to catch systematically, and a reason to
  expect materially better reliability once this runs against Groq's
  70B model instead of a local 8B one.

**Slice 1 status: done.** All checkboxes above are checked; the agent
answers real questions end-to-end through the HTTP API, backed by real
ingested data, with a verified self-correction loop and a verified safety
boundary.

---

## Slice 2 — RAG over the schema

**Date:** 2026-08-24

### What changed structurally

Slice 1's `GAMES_TABLE_DESCRIPTION` was one hardcoded string, always
injected into the system prompt whole. Slice 2 replaces it with:

- `src/agent/rag/schema_corpus.py` — the same facts, broken into small
  independent `SchemaChunk`s: one per table (a one-line orientation), one
  per column, and a handful of "metric notes" for gotchas that aren't tied
  to a single column (unit conversions, the owners-midpoint convention, the
  no-UNION rule).
- `src/agent/rag/embeddings.py` — an embedding-provider seam, structurally
  identical to `llm_provider.py`'s `get_llm()`: one config value
  (`EMBEDDING_PROVIDER`), everything else just calls `get_embedder()`.
- `src/agent/rag/schema_index.py` — a brute-force in-memory cosine-similarity
  index over the ~24 chunks, plus `assemble_schema_text()` to turn a
  retrieved chunk list back into prompt text.
- A new graph node, `retrieve_schema`, now the entry point:
  `retrieve_schema -> agent -> execute_tools -> agent -> ... -> END`. It
  embeds the question, retrieves the top-K chunks, and builds the system
  prompt from only those — same "make it a visible node" principle as
  Slice 1's self-correction loop, so it's traced and explainable, not
  implicit setup.
- `/ask` now also returns `retrieved_schema_chunks` — which chunk IDs the
  retrieval step actually picked for that question. Cheap to add, and it
  turns "trust me, RAG is working" into something you can see per request.

### Embedding provider: why fastembed, not sentence-transformers or a hosted API

Groq has no embeddings endpoint, so "reuse whatever `MODEL_PROVIDER` is
configured" was never on the table — this needed its own decision.
Considered three options:

- **sentence-transformers** (torch-based): the most common choice, but
  pulls in torch as a dependency — heavy (hundreds of MB), and a poor fit
  for a project that's explicitly trying to stay deployable on free-tier
  serverless hosting (Slice 6's open question).
- **A hosted embeddings API** (OpenAI/Cohere/etc.): adds yet another API
  key and a per-request network dependency for something that, at this
  corpus size (~24 chunks), doesn't need to be hosted at all.
- **fastembed** (chosen): ONNX runtime, no torch, small model
  (`BAAI/bge-small-en-v1.5`, ~130MB, quantized), runs in-process. No API
  key, works identically in dev and wherever this ends up deployed. Ollama
  embeddings (`nomic-embed-text`) are wired in as the local-dev alternative
  via the same seam, matching the pattern already established for the chat
  model, but fastembed is the default specifically because it has no
  runtime dependency on a separate daemon being up.

### Same TLS issue, different library — and a cleanup

fastembed's first run failed with the identical
`SSLCertVerificationError` from Slice 1 (Avast TLS interception), this
time on `huggingface_hub`'s model download (via `httpx`, not `requests`).
`truststore.inject_into_ssl()` fixed it the same way. Since this is now
the second independent HTTP client hitting the same problem, moved the fix
out of `steamspy_client.py` and into `src/config.py` (imported by nearly
everything) so it applies once, process-wide, instead of being duplicated
per-module that happens to make HTTP calls.

### Retrieval-quality testing found two real gaps — and they taught something

Tested retrieval directly (not just "does the agent still answer
correctly") by embedding sample questions and inspecting which chunks
ranked in the top-K, before ever wiring it into the graph. Two systematic
misses, both the same underlying cause:

- *"How many owners does Palworld have?"* did not retrieve `column:name`
  in the top 8 (it ranked ~13th).
- *"average playtime ... RPG games"* and *"games tagged as Action"* did
  not retrieve `column:genre` in the top 8 on either question (independent
  tests, same gap).

Root cause: a small bi-encoder embedding model measures semantic
similarity between the *question text* and the *chunk text*. A specific
value — a game's actual name, a specific genre string — doesn't embed
close to a generic column description ("Game title", "comma-separated
genres"). The words that would make the match ("Palworld" is a name; "RPG"
is a genre) aren't in the chunk at all. This is a known-in-the-literature
limitation of pure dense retrieval on short, generic schema text, and I
was glad to catch it empirically with a print statement before assuming
retrieval was "done" just because the agent's answers looked fine.

Fix: added an `always_include` flag to `SchemaChunk`, set on `table:games`,
`column:name`, and `column:genre` — chunks that bypass ranking and are
always present regardless of similarity score. This is deliberately
*not* "always include everything" (that would defeat the point of doing
RAG at all) — it's reserved for chunks that are structurally relevant to
nearly any question (every answer is about specific game(s); genre is one
of the most commonly filtered dimensions here), decided from two
independent failing test questions per column, not from tuning to make
one example pass.

**What this proved, interestingly:** *before* the `column:name` /
`column:genre` fix, the agent still answered the RPG playtime question
correctly — Llama 3.1 8B guessed a column named `genre` existed from
general knowledge of how game databases are usually modeled, wrote a
working query, and it happened to be right. That's a fragile thing to rely
on (a less conventional schema would have broken it), not evidence that
retrieval quality doesn't matter. Worth being honest about: the fix was
made because the *retrieval* was wrong, independent of whether the LLM
covered for it that particular time.

### Real finding: SteamSpy's playtime data is 0 across the entire dataset

While testing the playtime question, the agent reported "0 hours" for
average RPG playtime. Checked the raw data directly rather than assuming
it was a query bug:

```
nonzero avg playtime forever: 0 / 200 games
nonzero avg playtime 2weeks:  0 / 200 games
```

Every single ingested game has `average_playtime_forever_min = 0`. Not an
ingestion bug — this is a documented SteamSpy limitation: since a 2018
Steam privacy API change, SteamSpy has largely been unable to compute
playtime statistics, and the field is 0 for the overwhelming majority of
games in the modern API. Confirmed the raw cached `appdetails` JSON in
`data/raw/` shows `average_forever: 0` straight from the source, not
something introduced by `_row_from_appdetails()`.

Fixed the right layer: this isn't a code bug to patch, it's a data
limitation the agent should disclose. Added a `metric:playtime_often_zero`
chunk to the RAG corpus describing exactly this, and re-tested — the
agent's answer changed from a bare, misleading "0 hours" to "0 hours, due
to a known SteamSpy data limitation..." once that chunk was retrievable.
This is a good demonstration of what RAG-over-metrics is actually *for*:
not just column definitions, but domain caveats a real analyst would know
and a model wouldn't, unless told.

### Reinforcing the Slice 1 finding: small local model, same failure class, different shape

Re-ran all three Slice 1 example questions as a regression check.
Highest-rated and highest-CCU both still correct. The Action-vs-F2P price
comparison — already flagged in Slice 1 as a small-model weak spot — was
wrong *again*, but in a different way this run: it dropped the
`CASE WHEN` filter entirely for the free-to-play side and computed
`AVG(price_usd)` over *all* games, mislabeling the result as
`avg_f2p_price`. Same query pattern, non-deterministic failure mode,
consistent with Slice 1's note that this is Llama 3.1 8B's reasoning
reliability, not a guard or retrieval problem — retrieval correctly
surfaced `genre`, `price_usd`, and the `metric:no_union` note for this
question. Deliberately did not chase this with another prompt patch:
that's exactly the kind of failure the Slice 5 eval harness exists to
catch systematically (across many questions and repeated runs) rather than
whack-a-mole fixing one observed instance at a time.

### Open questions (new)

- **Retrieval evaluation is still eyeballed**, not scored. Slice 5's eval
  harness should include retrieval-quality checks (did the right chunks
  get retrieved for a golden question set), not just end-to-end answer
  correctness.
- **`always_include` is a manual escape hatch.** Fine at ~24 chunks with 2
  forced inclusions; if more tables/columns need this later, it's worth
  asking whether that's a sign the embedding model or chunk phrasing needs
  improving rather than adding more manual overrides.
- **fastembed's model cache is process-local disk, not committed.** First
  run on a fresh machine (or deployment) pays a ~130MB download + ~10s
  init cost. Fine for local dev; worth remembering for Slice 6 (cold-start
  latency on serverless would make this worse — another data point for the
  deployment-target decision).

---

## Slice 3 — Supervisor-router

**Date:** 2026-08-24

### What changed structurally

Added `src/agent/router.py` and a new `router` node, now the graph's entry
point:

```
router -> [lookup/analysis]     -> retrieve_schema -> agent <-> execute_tools -> END
        -> [forecast]           -> forecast_not_supported                     -> END
        -> [needs_clarification]-> ask_clarification                          -> END
```

The router classifies the question into one of four categories using the
LLM's structured-output feature (`with_structured_output(RouteDecision)`,
a Pydantic model with a `Literal` field) rather than a free-text prompt
parsed by hand — the result is always one of exactly four valid values,
no guarding against the model inventing a fifth category or wrapping its
answer in prose needed.

### An honest scoping call: lookup and analysis share a backend today

The four categories are real and independently tested, but only two
distinct *behaviors* exist behind them right now:

- `lookup` and `analysis` both go to the existing `retrieve_schema ->
  agent -> execute_tools` SQL pipeline — the same one, unchanged. That's
  because Slice 4's dedicated statistical-analysis tool (cohorts,
  significance, anomalies) doesn't exist yet; until it does, "analysis"
  and "lookup" are both, mechanically, "write a SELECT and answer." The
  classification is genuine and already correctly distinguishes a
  ranking/filter question from a cross-group comparison — giving
  `analysis` its own handler in Slice 4 is a small additive change to
  `route_after_router`, not a redesign.
- `forecast` and `needs_clarification` get genuinely new, distinct
  behavior: an honest "I can't do that yet" and a clarifying question,
  respectively — neither existed at all before this slice. Before the
  router, a forecast question would have gone straight into the SQL
  agent, which has no time-series data or forecasting logic and would
  have either produced a nonsense query or a confidently wrong answer
  from whatever it managed to compute. Same for an ambiguous question
  like "Is this game good?" — previously the agent would have just
  guessed at a game and answered as if the question were unambiguous.

Called this out explicitly rather than silently merging lookup/analysis
and hoping nobody asks: it's a genuine, deliberate sequencing decision
(build the router before the tools it'll eventually differentiate
between), not a shortcut passed off as complete.

### Testing: classification in isolation, then the full graph, then live HTTP

Same three-layer discipline as Slices 1 and 2 — didn't just check "does
the agent still answer questions."

1. `classify_question()` directly against 4 hand-picked questions (one per
   category, including an intentionally ambiguous one: "Is this game
   good?"). All 4 classified correctly on the first try, and the
   clarifying question generated for the ambiguous one was sensible
   ("What is the name of the game you are referring to?").
2. Full graph via `run_agent()` for the same 4 questions — confirmed
   `route` is populated correctly, confirmed `sql`/`retrieved_chunk_ids`
   are `None` for the forecast and clarification branches (they never
   reach `retrieve_schema`, which is the intended "don't even attempt a
   query" behavior, not a bug), and confirmed the lookup/analysis
   questions still work through the unchanged SQL pipeline underneath.
3. Live HTTP: `POST /ask` with the ambiguous question, confirmed
   `route: "needs_clarification"` and `retrieved_schema_chunks: null` come
   through the API correctly.

Notably, the Action-vs-free-to-play comparison question — flagged in both
Slice 1 and Slice 2 as an unreliable pattern for the local 8B model — came
back *correct* this run. Consistent with the standing conclusion: this is
non-deterministic small-model reliability, not a bug in the guard,
retrieval, or now the router. Still a Slice 5 (eval harness) problem, not
something to keep manually re-testing and hoping for the best on.

### A real interruption, and how it was handled

Mid-testing, the local Ollama runtime crashed (`CUDA error: shared object
initialization failed`) — a transient GPU/driver issue in the Ollama
process itself, unrelated to any code in this repo. Killed both
`ollama.exe` processes and let Ollama's own launcher restart them; the
next request succeeded normally. Noting this mainly as a reminder for
Slice 6: whichever deployment target gets picked, it won't be running a
local GPU-backed Ollama daemon — this class of failure is specific to the
local-dev provider path and shouldn't recur against Groq's hosted API.

### Open questions (new)

- **The router adds one extra LLM round-trip per question**, before any
  DB work happens. Cheap relative to the SQL agent's own calls, but worth
  measuring once there's real latency data (Slice 5/6) — a small/fast
  model dedicated to routing (vs. reusing whatever `MODEL_PROVIDER` is
  configured for the main agent) could be a worthwhile split later if
  routing latency turns out to matter.
- **No test yet for a question that's genuinely borderline between
  lookup and analysis.** The four hand-picked test questions were chosen
  to be unambiguous examples of their category; real user questions won't
  always be this clean. Another concrete case for Slice 5's golden
  question set.
