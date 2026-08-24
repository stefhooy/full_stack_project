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

---

## Slice 4 — Specialized analysis tools (stats + viz; forecast deferred)

**Date:** 2026-08-24

### Scoping call: forecasting is not built this slice

The original plan bundles statistical analysis, forecasting, and
visualization into one slice. Built two of three. Forecasting needs
something to forecast *over* — time-series data — and none exists yet;
that's Slice 7's `player_counts` table. A "forecasting tool" today would
have nothing real to operate on. Building one anyway (e.g. a fake linear
extrapolation over a single current-snapshot number) would be decorative,
not real functionality, and this project is explicitly about working
end-to-end slices, not stubs that look like coverage. The router's honest
"can't forecast yet" response from Slice 3 stays as-is; a real forecasting
tool is now explicitly tied to Slice 7 in PLAN.md rather than left dangling
under Slice 4.

### run_stats: three modes chosen for what SQL genuinely can't do well

DuckDB already has real statistical aggregates built in (`corr`, `stddev`,
`quantile_cont`, etc.), so a stats tool that just re-implements `AVG`/`STDDEV`
would be redundant. `src/tools/stats_tool.py` covers what plain SQL
aggregates don't: a real hypothesis test with a p-value
(`compare_two_groups`, Welch's t-test + Cohen's d via `scipy.stats`,
chosen over the equal-variance Student's t-test as the safer default when
group variances aren't known to be equal) and z-score outlier flagging
(`outliers`) — DuckDB has no significance-testing primitive at all, and
while it *could* compute z-scores via a window function, the
interpretation/thresholding logic is cleaner in Python than SQL.
`describe` rounds out the set for plain summary stats.

Every mode runs its query through the same guarded, read-only connection
as `run_sql` (`run_guarded_query`) — this tool is not a bypass of the
SELECT-only/allowlist guard, it's "SQL in, statistics out."

### Closing the loop from Slice 3: analysis finally gets a different toolset

Slice 3's DOCEXP entry flagged this explicitly: "`lookup` and `analysis`
both go to the same backend... giving `analysis` its own handler is a
small additive change to `route_after_router`, not a redesign." That
change landed here: `agent_node` now binds `[run_sql]` for `lookup` and
`[run_sql, run_stats]` for `analysis` (`_tools_for_route()` in graph.py).
The router isn't just a label anymore — it gates what the model is even
capable of doing for a given question.

### Testing: tools in isolation against real data, then the full graph

Same discipline as every prior slice. Ran all three `run_stats` modes
directly against the real 200-game dataset before ever wiring them to an
LLM:

- `compare_two_groups` (Action vs. everything else, price): t = -0.365,
  p = 0.716 → correctly not significant, tiny effect size (Cohen's d =
  -0.059). Sanity-checked by hand: means of $17.81 vs $18.94 are close, so
  a non-significant result is the right answer.
- `outliers` (peak_ccu, z > 2.5): flagged Counter-Strike: Global Offensive
  (z ≈ 13) and PUBG (z ≈ 3.9) — both obviously legitimate standouts, not
  false positives.
- `describe` (review_score): sane bounded output (mean ≈ 0.85, correctly
  within the 0..1 fraction range documented in the RAG corpus).

Then ran real questions through the full graph and live HTTP, including
the exact Action-vs-free-to-play question that's been unreliable since
Slice 1.

### The comparison question, revisited: better tool, more visible failure

With `run_stats` available, the model correctly reached for
`compare_two_groups` *without being asked for significance explicitly* —
progress. The computed statistics were internally correct (t-test, p-value,
Cohen's d all check out against the query it actually ran). But the
query itself mislabeled a group:

```sql
SELECT CASE WHEN genre LIKE '%Action%' THEN 'action' ELSE 'free_to_play' END AS group_label,
       price_usd AS value FROM games
```

The `ELSE` branch is labeled `'free_to_play'` but never checks
`price_usd = 0` — it's actually "everything that isn't Action," which
includes plenty of paid games. The tool computed a perfectly correct
p-value for the wrong comparison, and the final answer ("free-to-play
games average $18.94") was confidently, fluently wrong.

This was only catchable because of a transparency field added *because of*
finding this bug: `AgentResult`/`/ask` didn't originally expose the actual
query behind a stats result the way `sql` does for `run_sql` — added
`stats_query` specifically once this looked suspicious, and it immediately
confirmed the mislabeling. Kept the field permanently: without it, this
class of bug is invisible in the API response — a well-formatted, correct-
looking p-value with no way to check what it was actually computed over.

Tried the direct fix: added an explicit warning to the analysis tool
guidance ("a catch-all ELSE must be labeled generically, not with a name
implying a filter you didn't apply — e.g. `ELSE 'free_to_play'` is WRONG
unless that branch checks price_usd = 0"). Re-ran the identical question:
**same mislabeling, same wrong answer**, word-for-word identical query.
Consistent with the standing conclusion since Slice 1 — this is Llama 3.1
8B's reliability ceiling on this specific pattern, not something more
prompt text fixes. Kept the guidance anyway (real, correct instruction,
worth having for whatever model reads it — likely more effective against
Groq's 70B), logged the negative result rather than hiding it, and did not
keep iterating on the prompt. This is precisely the kind of thing Slice 5's
eval harness needs to catch systematically (run N times, measure the
mislabel rate) instead of one more manual spot-check.

### A real bug, unrelated to model quality: string-typed tool args

Testing the `outliers` mode through the full graph crashed:
`numpy._core._exceptions._UFuncNoLoopError` comparing a float array against
`z_threshold`. Root cause: Ollama's function-calling returned `z_threshold`
as the JSON string `"2.5"` rather than a number, despite the tool schema
declaring it a float — LangChain passes tool-call args through mostly
as-received. This is not a reasoning failure, it's an interface contract
the LLM's tool-calling layer didn't honor. Fixed at the tool boundary
(`execute_run_stats` now does `z_threshold = float(z_threshold)` before use)
rather than trusting the declared schema type — same "validate at the
boundary, don't trust what arrives" principle as the SQL guard, just
applied to argument *types* instead of query *safety* this time.

### Chart-spec generation: deliberately not an LLM call

`src/tools/viz_tool.py::infer_chart_spec()` looks only at the shape of a
successful query result — column count, and whether each column's actual
Python values are numeric or not — to pick bar/scatter/table. This is a
mechanical decision with one correct answer given the shape, so there's no
ambiguity to spend an LLM call resolving; it runs as a plain function in a
new `build_chart_spec` graph node after a successful `run_sql` result, not
as a bindable tool. The spec shape (`{type, x, y, data}`) is deliberately
framework-agnostic — not tied to Vega-Lite/Chart.js/Recharts — so it
doesn't need to change once Slice 6 picks a frontend charting library.

### Open questions (new)

- **The mislabeled-group failure mode is now visible but not prevented.**
  `stats_query` makes it auditable; nothing yet stops the wrong answer
  from reaching the user. Options for later: a lightweight sanity check
  (does a labeled group's aggregate match what the label claims — e.g. if
  a group is labeled `free_to_play`, assert its mean price actually is ~0
  before trusting the label) or just leaning on Slice 5's eval harness to
  quantify how often this happens and whether Groq's larger model avoids
  it.
- **Chart-spec heuristics are untested against a genuinely wide variety of
  query shapes** — validated against the two shapes Slice 4's example
  questions naturally produce (name+numeric, label+numeric). Three+ column
  results and time-series-shaped results (once Slice 7 lands) aren't
  handled yet — currently fall back to `None` (table view) rather than
  guessing.
- **`run_stats`'s modes require the LLM to shape its query correctly**
  (exactly 1 or 2 columns, right order) — same class of risk as any
  LLM-authored SQL. The self-correction loop catches shape errors (they
  raise `ValueError`, which is caught the same way SQL errors are), but a
  golden-question eval would quantify how often that's actually needed.

---

## Slice 5 — Eval harness

**Date:** 2026-08-24

### Built specifically to answer two open questions from Slice 4

Slice 4 ended with two things I couldn't answer from a single manual test:
how *often* the group-mislabeling bug happens, and whether it's specific
to the local 8B model. This slice exists to answer both — not as a
generic "add an eval harness" checkbox, but pointed at a real, previously
observed defect.

### Design: live ground truth, not hardcoded numbers

`src/evals/golden_questions.py::build_golden_questions()` is a function,
not a module-level list — it queries the live DuckDB file for every
reference fact (top peak_ccu game, count of games with review_score > 0.9,
count of free-to-play games) at eval time. Considered hardcoding expected
values instead (simpler, no DB dependency at eval time) and rejected it:
ingestion is idempotent and re-runnable, prices/reviews/owners can change
on a re-ingest, and a hardcoded "expected 47 games" would silently go
stale the next time someone runs `python -m src.ingestion.ingest` and
start failing the suite for the wrong reason (data drift, not a real
regression). Computing ground truth live means the suite is always
checking "does the agent's answer match what's actually in the database
right now" — the only check that stays meaningful over time.

### The bug-specific check, not a generic one

The eval that targets Slice 4's mislabeling bug
(`_check_action_vs_f2p_not_mislabeled` in golden_questions.py) doesn't
compare the agent's stated conclusion to a reference conclusion — it
checks a fact the agent's own claimed label logically implies. Free-to-play
means price = 0 *by definition*; a group the agent calls "free-to-play"
must have a mean price of ~$0, full stop, regardless of what p-value or
comparison it's embedded in. This is a stronger check than "does the
number match the expected number" — it doesn't need to know the correct
number in advance, it just needs the agent's own label to be internally
consistent with the data. Worth being explicit about, because it's the
difference between an eval that would have caught this specific bug
reliably and one that happens to catch it by luck.

### Results against Ollama (llama3.1:8b) — same tool used for every prior slice

```
route accuracy:        6/6
deterministic checks:  5/6
avg judge score:       4.3/5
```

The one failure is exactly the Slice 4 bug, caught by both signals
independently:
- Deterministic check: `group 'free_to_play' claims to be free-to-play but
  has mean price $18.93 (should be ~$0 by definition)`.
- LLM judge (unprompted with any knowledge of the deterministic check):
  score 1/5, rationale *"contradicts the reference facts by stating that
  free-to-play games have an average price of $18.94, which is higher than
  the actual mean price of $0.00."*

Two independently-built signals — one a hand-written numeric assertion,
one an LLM given only the question/answer/reference-facts — converging on
the identical diagnosis is a good sign the check design is sound, not
just tuned to pass on this one run.

**The second open question — whether this is specific to the local 8B
model — is still open.** No Groq key available in this environment to test
against the 70B default. `python -m src.evals.run_evals` is exactly the
command to run once a key is added; the harness was built so answering
that question is "run one command," not "write new test code."

### Why the judge doesn't gate the exit code

Deliberately made `run_evals.py`'s exit code depend only on route
correctness + deterministic checks, not the judge score. The judge is a
second opinion, useful for catching wording/clarity issues the
deterministic checks don't anticipate — but it's still an LLM call with
its own sampling noise, and a "regression check" that can flip pass/fail
on unrelated LLM variance defeats the purpose of having one. The
deterministic checks are the gate; the judge is a report.

### Open questions (new)

- **Six golden questions is a start, not full coverage.** One per route
  plus the two Slice 4-specific regression checks. No coverage yet for
  malformed/adversarial input, multi-part questions, or the RAG retrieval
  quality gaps found in Slice 2 (that's a different kind of eval — scoring
  retrieved chunks against expected chunks — not yet built here).
- **No repeated-run variance measurement.** Ran the suite once per
  provider tested. Given Slice 1-4's evidence that the local model's
  failures are non-deterministic (same question, different wrong answer
  across runs), a single run understates the true failure rate in either
  direction. Running N=5-10 times per question and reporting a pass rate
  would be a more honest reliability number — noted as a natural next
  improvement, not done here to keep this slice thin.
- **No CI wiring yet.** The harness is runnable and has a real exit code,
  but nothing invokes it automatically. Natural fit once there's a CI
  pipeline (implicitly, whenever the deployment slice sets one up).

---

## Slice 6 — Frontend + deploy

**Date:** 2026-08-24

### Resolving the hosting decision, finally

Flagged as open since Slice 1's very first DOCEXP entry: Vercel Python
functions vs. Vercel frontend + a separate Python host. Resolved this
slice by actually looking at what this stack needs, not just picking one:
fastembed's ONNX model (~130MB), scipy, a DuckDB file, and an agent that
can make 2+ sequential LLM calls with retries (10-30s+ isn't unusual, as
directly observed throughout Slices 1-5). Vercel Hobby's Python functions
cap around 250MB unzipped and ~10s execution — this stack would be fighting
both limits from day one. Chose **Vercel for the frontend, Render or
Fly.io (a normal long-running Python process) for the backend** instead.
This is exactly why `src/agent` and `src/db` never import FastAPI (a
decision made explicit as far back as Slice 1's README) — the entire
hosting decision only ever touched `src/api/main.py` and new files
(`Dockerfile`, `render.yaml`), never the agent logic itself.

### Streaming: per-node progress, not token-level

`stream_agent()` (src/agent/graph.py) uses LangGraph's
`astream(stream_mode="updates")` to yield after each node completes,
mapped to a human-readable message ("Classifying your question...",
"Running query..."). Considered token-level streaming of the final answer
instead (more common for chat UIs) and deliberately didn't: this agent's
useful latency isn't in generating the final sentence character-by-character,
it's in the multi-step pipeline before that (routing, retrieval, tool
calls, retries) — a token-level stream would sit silent through most of
that and then dump the whole answer at once anyway. Node-level progress
events match what's actually slow, and match the project's standing
design principle that every step should be a visible, nameable thing
(same reasoning as making the self-correction loop and RAG retrieval real
graph nodes back in Slices 1 and 2) rather than an opaque wait.

Implementation note: `stream_agent` manually accumulates node updates into
a plain dict rather than replicating LangGraph's internal state-merging
logic — works correctly here specifically because every node in this graph
returns only *new* values (the messages list) or the *current* full value
(everything else), never something needing a custom merge beyond
last-write-wins. Verified directly (not just assumed) before relying on it:
ran `stream_agent()` standalone and confirmed the final answer text matched
`run_agent()`'s answer for the same question.

### Semantic cache: calibrated, not guessed

`src/agent/cache.py` reuses the Slice 2 embedding provider seam — cosine
similarity between question embeddings, in-memory. Picked an initial
similarity threshold of 0.96 without measuring anything, then actually
measured before shipping it: a clear paraphrase of a cached question
("most owners" vs. "highest number of owners") scored 0.957 — just under
0.96, meaning the "obvious" threshold would have missed the single most
common real-world cache scenario (someone rephrasing the same question).
A related-but-different question ("most players" vs. "most owners") scored
0.834, and an unrelated question scored 0.481. Lowered the threshold to
0.93 — clears the paraphrase, stays well clear of the related-but-different
case. Same discipline as Slice 2's RAG retrieval-quality testing: don't
ship a similarity threshold without checking what it actually does on a
real example.

### Rate limiting and graceful errors: both tested, not just written

Per-IP rate limiting (`src/api/rate_limit.py`, in-memory sliding window)
was verified with FastAPI's `TestClient` and the agent call mocked out
(so the test runs in under a second instead of waiting on 10+ real LLM
calls) — confirmed exactly 10 requests succeed, the 11th onward get 429.
Graceful error handling was verified the same way: patched `run_agent` to
raise, confirmed `DEBUG=false` (the default) returns the generic "high
demand" message while `DEBUG=true` returns the real exception — both
paths still log the full traceback server-side either way, so nothing is
lost for debugging, only what reaches the client changes.

### The frontend, and a live bug this testing actually caught

Built with Next.js 16 / React 19 (App Router, TypeScript, Tailwind v4).
`lib/api.ts` hand-parses the `/ask/stream` SSE wire format from a plain
`fetch()` `ReadableStream` rather than using the browser's `EventSource` —
`EventSource` only supports GET, and the question has to go in a POST
body. `components/Chart.tsx` follows the project's dataviz skill: single
hue (every question produces at most one series, so no legend needed —
the heading names it), colors from the validated default palette's
series-1 slot as CSS custom properties (light/dark both defined), thin
bars with rounded top corners, recessive gridlines.

Tested by actually launching the app and driving it with Playwright
(`chromium.launch()`, no `chromium-cli` available in this environment) —
not just `npm run build` succeeding. This caught a real bug: the first
click through the UI returned the graceful "high demand" message instead
of a real answer. Traced it to the backend log rather than assuming the
frontend was broken: another **Ollama CUDA crash**, the same transient
GPU/driver issue from Slice 3, this time hitting the `router` node.
Restarted Ollama (same fix as before) and re-tested successfully — and
this incidentally validated the graceful-error feature working exactly as
designed under a real failure, not a synthetic one: friendly message to
the browser, full traceback in the server log.

### A rendering mystery, chased properly instead of guessed at

The rendered example-question buttons showed what looked like rainbow/
chromatic-fringed text in every screenshot. Didn't assume and didn't
guess-fix:
1. First hypothesis: missing an explicit text-color class (the buttons
   had no `text-*` utility). Added one. **No change** — which is itself
   informative, not a wasted step.
2. Checked `getComputedStyle` directly rather than trust the screenshot:
   `color: lab(27.036 0 0)` — a single, flat, uniform gray. Proves the
   CSS was already correct; whatever's happening isn't the `color`
   property.
3. Suspected Playwright's default headless-only "Chrome Headless Shell"
   browser (a stripped-down variant, not full Chromium) might not fully
   support the modern `lab()`/`oklch()` color functions Tailwind v4
   generates by default. Tested against the system's real installed
   Chrome via `channel: 'chrome'` — **same artifact**, ruling that out.
4. Tested fully non-headless (a real, visible browser window, not
   headless emulation) — **still the same artifact**, ruling out
   anything headless-specific at all.

Conclusion: this is subpixel/ClearType antialiasing on small text — a
real, well-known phenomenon where a screenshot captured and viewed
pixel-for-pixel shows the individual R/G/B subpixel fringes that a
physical LCD panel and the human eye's optical blending are designed to
merge into smooth gray. It's not something a real user looking at a real
screen would perceive as "rainbow text" — it only shows up because a
screenshot is a literal pixel capture, not an optically-blended view.
Confirmed this is a screenshot-viewing artifact, not a product bug, only
after four independent checks each ruling out a different cause — worth
recording the process, not just the conclusion, since "it looked like a
CSS bug and turned out not to be one" is exactly the kind of thing worth
being able to explain rather than silently having fixed (or worse,
silently having ignored a real bug because it "probably wasn't important").

### Deployment config: written carefully, not verified live

`Dockerfile` runs ingestion **at build time** — a deliberate trade-off for
a mostly-static demo dataset (bakes a SteamSpy snapshot into the image;
re-deploy to refresh) rather than needing a persistent volume or an
external data store for what's currently ~200 rows. `render.yaml` mirrors
`.env.example`'s settings as a Render Blueprint. Neither is verified
against a live build or a live Render/Fly account — no Docker available in
this environment, and per the earlier scoping conversation, the user is
deploying manually. Said so plainly in the README's Deploying section
rather than implying these are tested when they aren't.

### Open questions (new)

- **The Dockerfile is unverified.** First real test is the user's actual
  deploy. If `libgomp1` isn't actually what onnxruntime needs on the
  platform's base image, or if build-time network access to steamspy.com
  is restricted on some platform, the ingestion `RUN` step would need
  adjusting — flagged as the most likely failure point, not silently
  assumed to be fine.
- **No scheduled data refresh.** The deployed backend's catalog is frozen
  at whatever the image build saw. Revisit once Slice 7 builds real
  scheduling infrastructure (GitHub Actions cron) for the player-count
  poller — reusing that mechanism for a periodic SteamSpy re-ingest is a
  natural, cheap extension at that point, not before.
- **CORS is a manual two-way env var handoff** (backend needs the
  frontend's URL, frontend needs the backend's URL, and the frontend's
  URL isn't known until after the frontend is deployed). Fine for a
  single deployment; would want automating if this had a staging
  environment too.

---

## Slice 7 — Live player-count time series

**Date:** 2026-08-24

### Two tables, two different freshness contracts

`player_counts` isn't just "another table" — it has the opposite data
character from `games`. SteamSpy's catalog reflects *current* state: every
re-fetch overwrites what we knew, and there's zero value in an old
snapshot (that's why `games` ingestion has always been UPSERT). Steam's
live player-count endpoint has no history API at all — every poll captures
a moment that can never be recovered later. That difference drove every
design decision this slice: `games` is rebuilt fresh each run;
`player_counts` only ever accumulates, and the raw polls themselves
(not just the derived table) have to be preserved *somewhere durable*,
because they're the only copy of that history that will ever exist.

### Why polling and table-building are two separate scripts

GitHub Actions runners are ephemeral — nothing written to a local file
during one scheduled run survives to the next. So persistence has to
happen through something that *does* persist: git. `poll_player_counts.py`
does exactly one thing — fetch live counts, write a timestamped JSON
snapshot, done. A separate script, `build_player_counts_table.py`, rebuilds
the actual DuckDB table by replaying *every* committed snapshot
(idempotent — `ON CONFLICT (appid, polled_at) DO NOTHING`). This is the
same collect-raw-then-build split already established for SteamSpy in
Slice 1 (`steamspy_client.py` caches to disk, `ingest.py` builds the table
from it), applied for a different reason: there, the cache is a
performance/idempotency shortcut; here, the raw snapshots *are* the
durable data — the DuckDB table is the disposable, always-regenerable
artifact, same as `games` always was.

### Verified the "no API key" assumption before building around it

Steam's docs are inconsistent about whether `GetNumberOfCurrentPlayers`
needs a key. Curled it directly first: `?appid=730` returns real data with
no key, `?appid=999999999` returns `{"result": 42}` (no data, but still
HTTP 200). Built the client around that — then hit a *third* response
shape in the actual 200-game poll run that the two-appid spot check
didn't surface: a real, currently-catalogued appid returned a bare
**404**, not the `result != 1` pattern. `resp.raise_for_status()` crashed
the entire batch on that one appid. Root cause, best guess: SteamSpy's
index and Steam's live store don't perfectly agree on what still exists —
a game can be delisted from Steam while still sitting in SteamSpy's
catalog. Fixed by treating a 404 the same as `result != 1` (skip this game,
keep going) while still letting real connection failures (timeouts, 5xx)
propagate and fail the run loudly — the same "some failures should skip,
some should stop everything" judgment call as `sql_tool.py`'s error
handling, just for a different kind of error. 199/200 games polled
successfully after the fix; the one skip is correct, not a bug.

### The payoff: zero agent code changed

Added `player_counts` to `ALLOWLISTED_TABLES`, added its RAG corpus
chunks, and — nothing else. Asked the agent *"What is the current live
player count for Counter-Strike: Global Offensive?"* and it correctly
wrote the join and answered right, with no change to graph.py, no new
tool, no new route. This is exactly the payoff `schema.py`'s very first
comment (Slice 1) promised: "this file is named schema.py and not
games_table.py — it's meant to grow." Three slices later, growing it
really was this cheap.

### A real regression from adding a second table — caught and quantified, not just noticed

Re-ran the full eval suite after adding `player_counts` (same discipline
as every slice: don't just eyeball a few manual tests). A previously
*passing* question — the CCU outliers question — now failed:

```
before Slice 7:  deterministic 5/6, avg judge 4.3/5
after Slice 7:   deterministic 4/6, avg judge 3.7/5
```

Root cause, confirmed by checking retrieval directly rather than guessing:
`games.peak_ccu` ("peak concurrent players yesterday") and the new
`player_counts.player_count` ("live concurrent players right now") both
plausibly answer "concurrent players," and both got retrieved — this
wasn't a retrieval gap, `peak_ccu` was right there in the top-8. The model
picked `player_counts.player_count` but the first attempt wrote
`SELECT name, player_count FROM player_counts` — forgetting `player_counts`
has no `name` column, exactly the mistake the join note exists to prevent.
Added one more targeted RAG chunk explicitly disambiguating the two
columns and when to use which
(`metric:peak_ccu_vs_player_counts`).

**Partial fix, and said so honestly:** on retry, the model *did* write the
correct join this time — proof the disambiguation note worked for what it
targeted. But instead of emitting that corrected query as a real
structured tool call, it leaked the corrected query as prose with an
embedded pseudo-JSON blob ("It seems like the `name` column is actually
located in the `games` table... {"name": "run_stats", ...}") — a
degraded-tool-calling failure, not a schema-confusion one. Traced the full
message history (not just the final answer) to confirm this precisely:
message 2 was a real malformed tool call (schema confusion, the bug the
note targeted); message 4, after seeing the DuckDB error, contained the
*correct* query but as narrated text, not a function call. Two different
failure modes stacked in one run.

Did not chase the second one further. It reproduced deterministically
(temperature=0, identical output both times), which rules out random
sampling noise, but it's the same category of small-model tool-calling
unreliability documented since Slice 3 — a local 8B model narrating what
it would do instead of doing it, under multi-turn retry pressure. Worth
noting what *did* hold up despite the degraded output: the graph's
termination guarantee — no infinite loop, no crash, the retry-cap design
from Slice 1 worked exactly as intended even when the model's behavior
was unexpected. The failure is in answer quality, not system safety.

### Open questions (new)

- **`data/player_counts_raw/` now holds one real snapshot** from this
  session's local testing (199 games, genuinely polled from the live
  Steam API, not synthetic) — kept it rather than deleting it, since it's
  real collected data and gives a working demo a first data point before
  the scheduled workflow has ever run.
- **The peak_ccu vs. player_count disambiguation is unverified at scale.**
  Confirmed it changes behavior (the retry attempt got the join right),
  but the eval suite's `analysis_ccu_outliers` question still fails
  end-to-end because of the separate tool-calling issue — can't yet tell
  from one example whether the disambiguation note reliably prevents the
  *schema* confusion on a fresh (non-retry) first attempt. Another
  concrete case for running the eval suite N times once that's built out.
- **The two GitHub Actions workflows are unverified against a live
  GitHub repo** — no way to test a scheduled workflow, git push
  permissions, or a real deploy hook from this local environment. First
  real test is after the user pushes and enables Actions.
- **No cron-frequency tuning.** 6-hourly polling and weekly catalog
  refresh are reasonable starting guesses, not measured — worth revisiting
  once there's enough `player_counts` history to see whether 6h resolution
  actually shows interesting patterns (daily cycles, event spikes) or is
  needlessly frequent.
