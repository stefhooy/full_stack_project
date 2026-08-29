# DOCEXP — Engineering Log

A running lab notebook: decisions and why, what broke, what surprised me,
open questions. Written as I go, not after the fact. For the current
system's shape without the history, see [ARCHITECTURE.md](ARCHITECTURE.md).

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

---

## Interlude — requirements.txt → pyproject.toml + uv

**Date:** 2026-08-25

Not a slice, a packaging modernization requested mid-session once `uv`
was confirmed available. Replaced `requirements.txt` +
`requirements-ingestion.txt` with one `pyproject.toml` (+ committed
`uv.lock`), using `[project.optional-dependencies]` to formalize a split
that already existed informally: a lean base (everything
`src/ingestion/`, `src/db/`, `src/config.py` need — no LLM/RAG stack) and
an `agent` extra (FastAPI, LangGraph, LangChain, fastembed, scipy — what
`src/agent/`, `src/tools/`, `src/api/` need on top). GitHub Actions' poller
job now runs `uv sync` (base only); local dev and the Docker build run
`uv sync --extra agent`. Same intent as the two-file split, expressed as
one manifest that can't drift out of sync with itself the way two
hand-maintained files could.

`pyproject.toml` deliberately has no `[build-system]` table —
`[tool.uv] package = false` tells uv this is an application (run via
`python -m src.x.y`, imported as `from src.x import y`), not something
meant to be built into a distributable wheel. Worth being explicit about,
since the default assumption for a `pyproject.toml` is a real package.

**Third occurrence of the same Avast TLS problem, different tool this
time:** `uv lock` failed immediately with `invalid peer certificate:
UnknownIssuer` — the identical root cause from Slices 1 and 2
(`requests` and `fastembed`'s `httpx`/`huggingface_hub` calls), now
hitting uv's own Rust TLS stack, which `truststore` (a Python-only fix)
can't touch. uv has its own equivalent: `--native-tls` uses the OS trust
store instead of uv's bundled one. Set permanently via
`[tool.uv] native-tls = true` in `pyproject.toml` rather than requiring
the flag on every invocation — same "fix it once, centrally" instinct as
centralizing `truststore.inject_into_ssl()` in `src/config.py` back in
Slice 2. Three tools, three different TLS stacks, same underlying cause
each time, same "find the tool's own OS-trust-store escape hatch rather
than disabling verification" response each time.

**Verified, not just written:** ran `uv lock` (resolved 71 packages) and
`uv sync --extra agent` against the existing `.venv` (already `pip`-managed
from earlier slices) and confirmed uv reconciled it correctly — Checked 69
packages, no reinstall needed, since the dependency set matches what was
already there. Re-imported the app afterward to confirm nothing broke.
Also updated the Dockerfile to install `uv` as a static binary (copied
from its official distroless image) and use `uv sync --extra agent
--frozen` instead of `pip install -r requirements.txt` — faster and,
via `uv.lock`, pinned to exact resolved versions rather than whatever
`>=` ranges happen to resolve to on build day.

### Open questions (new)

- **The Dockerfile's uv-based build is unverified**, same caveat as the
  rest of the Dockerfile since Slice 6 — no Docker available in this
  environment to actually run the build.
- **`native-tls = true` is a machine-specific workaround being committed
  as a permanent project setting.** Harmless on machines without TLS
  interception (it just uses the OS store instead of uv's bundled one),
  but worth knowing it's there if uv behavior ever seems to silently
  trust something unexpected — it's a deliberate, documented choice, not
  a default.

---

## Interlude — real Groq key, and the standing question finally answered

**Date:** 2026-08-25

`llama-3.3-70b-versatile` (the model picked back in Slice 1) no longer
exists on Groq — `groq.NotFoundError: model_not_found`. Queried
`/openai/v1/models` directly rather than guess a replacement: Groq's
catalog now leans on OpenAI's open-weight GPT-OSS models
(`openai/gpt-oss-120b`, `-20b`) plus Groq's own `groq/compound` system and
a few others. Picked `openai/gpt-oss-120b` over `groq/compound`
deliberately — `compound` is itself an agentic system with built-in tools
(web search, code execution), and layering our own `bind_tools` orchestration
on top of a model that already has opinions about tool use seemed like
exactly the kind of hidden-behavior risk this project has avoided
everywhere else (no prebuilt agent constructors, no opaque tool-choice
logic). Verified tool-calling and `with_structured_output` both work
correctly against `gpt-oss-120b` before adopting it as the default.

**The eval harness finally got to answer the question it was built for.**
Ran it against real Groq for the first time: route accuracy 6/6, avg judge
score 4.5/5 — the highest of any provider tested. More importantly:
**zero occurrences of the group-mislabeling bug**, across both the direct
question and the eval run. `gpt-oss-120b` wrote genuinely correct
conditional-aggregation SQL (`AVG(CASE WHEN price_usd = 0 THEN price_usd
END)`, properly filtered) on every attempt. This confirms, with real
evidence rather than a hunch, what Slices 1 through 7 kept concluding
without being able to fully prove: the mislabeling bug was a Llama-3.1-8B
reliability ceiling, not an architecture, prompt, or guard problem.

The eval suite still reports 4/6 deterministic — but both "failures" are
eval-design gaps, not model errors, confirmed by re-reading what actually
happened: `analysis_action_vs_f2p_not_mislabeled`'s check specifically
requires a `compare_two_groups` stats_result (i.e. "did it call
run_stats"), and this run answered correctly via plain SQL instead — the
judge independently scored it 5/5 as factually correct. Same for the
outliers question: the judge marked it 2/5 for including PUBG as a second
outlier, but PUBG *is* a legitimate outlier at the z ≥ 2.5 threshold used
elsewhere in this project (confirmed via direct `run_stats` testing in
Slice 4) — the golden question's `reference_facts` just didn't mention
it, so the judge had no way to know. Left the golden questions unchanged
rather than patch them reactively; noted as the next real refinement
rather than declared "fixed" without re-verifying against multiple
providers again.

**A real, unrelated bug found and fixed along the way:** the eval
report crashed with `UnicodeEncodeError` printing `gpt-oss-120b`'s output
— it writes with proper Unicode typography (non-breaking hyphens, narrow
no-break spaces) that Windows' default console encoding (cp1252) can't
represent. Fixed by reconfiguring stdout to UTF-8 with replacement at the
top of `run_evals.py`. Not cosmetic — this would crash the harness on any
Windows machine the moment a model's output contained such characters,
which is exactly what happened.

### Open questions (new)

- **Golden-question checks are calibrated toward the failure mode a
  weaker model produced**, not the range of valid correct answers a
  stronger model can produce. `analysis_action_vs_f2p_not_mislabeled`
  should probably accept *either* a correctly-computed plain-SQL answer
  *or* a correct `run_stats` result — not require the tool call
  specifically. Worth revisiting once there's a reason to run evals across
  multiple providers routinely (Slice 5 already flagged this general
  shape of gap).
- **`groq/compound` untested.** Deliberately avoided it for the reason
  above, but never actually confirmed whether its built-in tool use would
  conflict with or complement this project's own `bind_tools` design —
  an assumption, not a measured result.

---

## Slice 8 — MCP server

**Date:** 2026-08-25

### Scope: dropped Gemini, sequenced the rest

User explicitly ruled out Gemini as a fallback provider (free-tier keys
expire too fast to be a reliable fallback) — removed it from the roadmap
rather than leaving it as a silently-stale TODO; the seam in
`llm_provider.py` stays (costs nothing to leave a branch that raises
`NotImplementedError`). The remaining Slice 8 items (MCP server, Expo
mobile) got split into their own slices with a proposed order: MCP first
(cheapest — mostly reusing code that already exists), frontend visual
polish next (highest-visibility ROI for a portfolio piece, and settling
on a look here makes the mobile UI faster later), Expo last (most new
surface area, and — worth flagging since cost keeps coming up — building/
testing it is free via Expo Go, but *publishing* to app stores isn't:
$99/yr Apple, $25 one-time Google. Recommended skipping store publishing
by default.)

### The SDK's API had moved since my training data — checked, didn't guess

Went to write the server using `from mcp.server.fastmcp import FastMCP`,
the pattern I expected from prior knowledge of the SDK. It doesn't exist
in the installed version (`mcp==2.1.0`): `ModuleNotFoundError`. Rather
than guess at a replacement, introspected the installed package directly
(`pkgutil.walk_packages`, then `inspect.signature` on candidates) and
found the successor: `MCPServer` in `mcp.server` — same decorator-based
API (`.tool()`, `.resource()`, `.run()`), just renamed and moved during
what looks like a significant SDK restructuring (also added
auth/OAuth support, an `apps` module, elicitation, subscriptions — a much
bigger surface than the version I remembered). Worth calling out as a
general lesson, not just an MCP-specific one: for a fast-moving SDK,
`inspect.signature()` against the actual installed version is more
reliable than remembered API shape, and took under a minute here.

### Reuse, not reimplementation — and proved it, not just claimed it

`src/mcp_server/server.py`'s `run_sql`/`run_stats` tools call
`execute_run_sql`/`execute_run_stats` directly — the identical functions
`src/agent/graph.py`'s `execute_tools` node calls. The safety guard
(`validate_select_only` in `src/db/connection.py`) is reached the same way
regardless of caller; there's no second implementation to keep in sync or
accidentally leave less-guarded. Didn't just assert this — verified it
with a real MCP client session (`ClientSession` over `stdio_client`,
spawning the actual server subprocess, not a mock): listed tools and
resources, read `schema://games`, ran a real query, and specifically sent
`DROP TABLE games` through the MCP `run_sql` tool and confirmed it comes
back with the same rejection message (`"Only SELECT statements are
allowed, got a Drop statement."`) an agent-driven query would get. Same
guard, same code path, proven rather than assumed.

### The schema resource reuses the RAG corpus, not a separate description

`schema://games` (an MCP *resource*, not a tool — read-only reference
data a client fetches once, not an action) calls
`assemble_schema_text(SCHEMA_CHUNKS)` from Slice 2's RAG module directly.
Considered writing a separate, MCP-specific schema description and
rejected it immediately: two hand-maintained descriptions of the same
schema is exactly the kind of drift risk this project has avoided
everywhere else (the RAG corpus itself exists specifically so the schema
is described in one place). The MCP resource gets the full, unfiltered
corpus (no retrieval/ranking — there's no "question" to rank against for
a static resource a client reads once up front), which is a fine, simple
default at this corpus's current size (~24 chunks).

### Why local stdio, not a hosted MCP server

Chose stdio transport exclusively for now, not `sse`/`streamable-http`
(both of which `MCPServer.run()` also supports). Stdio means: the client
(Claude Desktop, Claude Code) spawns the server as a local subprocess for
the duration of its own session — no hosting, no network exposure, no
cost, and no separate deployment decision to make. A hosted, remotely
reachable MCP server is a real possible future step (could piggyback on
the already-deployed backend, per the earlier deployment discussion), but
would need its own auth story (the SDK's new `auth`/OAuth module exists
for exactly this) — deliberately out of scope until there's an actual
reason to want the server reachable from somewhere other than the calling
app's own machine.

### Dependency placement: pragmatic, not maximally lean

Added `mcp[cli]` to the existing `agent` extra rather than a new,
narrower one. Considered a dedicated `mcp` extra (skip FastAPI/LangGraph/
LangSmith, which the MCP server genuinely doesn't use) and decided
against it: `src/mcp_server/server.py` already imports `src.tools.sql_tool`
(which imports `langchain_core` at module level for its own `@tool`-
decorated object, even though the MCP server never uses that object) and
`src.agent.rag.schema_index` (which imports the embedding provider,
pulling in `fastembed`, even though the MCP resource never calls it). A
truly lean MCP-only extra would need refactoring those modules to make
their heavier imports lazy — real, legitimate cleanup, but out of
proportion to what this slice needed, and the MCP server is inherently a
local-dev tool run on a machine that already has the full `agent` extra
installed to run the web app anyway. Noted as a real option, not pursued.

### Open questions (new)

- **No remote/hosted MCP transport.** Stdio-only for now; revisit if
  there's ever a concrete reason to want this reachable from outside the
  calling app's own machine (the SDK already has the auth pieces for it).
- **The lean-extra option for `src/tools/` and `src/agent/rag/` is real
  but unpursued** — `sql_tool.py` and `schema_index.py` both have
  heavier-than-necessary module-level imports for their MCP use case
  specifically. Worth doing if a genuinely lean, MCP-only install ever
  matters (e.g. distributing this as a standalone MCP server package
  independent of the web app).
- **Cursor untested.** Documented Claude Code and Claude Desktop config
  (both directly verifiable from this environment); Cursor's MCP config
  format is very likely close to Claude Desktop's (`mcpServers` JSON) but
  wasn't checked against a real Cursor install.

---

## Slice 9 — Frontend UI/design polish

**Date:** 2026-08-25

Slice 6 built the frontend's plumbing (SSE streaming, chart rendering, dark
mode via Tailwind's `dark:` classes) but deliberately left the visual design
plain — right call at the time, wrong call to leave standing once the rest
of the system had real content to show off. This slice is the visual pass,
requested explicitly with a "gaming AI" identity and real motion.

### One animation library, not four

The request that kicked this off named four animation libraries (Anime.js,
motion.dev, react-spring, Framer Motion) plus a couple of UI-kit references.
Framer Motion *is* motion.dev — Framer Motion was renamed "Motion" and now
ships from the `motion` package, same author, same lineage — so two of the
four names were the same library twice. Running Anime.js, react-spring, and
Motion side by side in one app would mean three animation engines' worth of
bundle weight and three different easing/spring feels for no real gain, so
the app standardizes on Motion (`motion/react`) alone. Same reasoning for
"Kokonut UI": it's a copy-paste component registry (shadcn-style — you
`npx shadcn add` a component's source into your own tree), not an
installable package, so there's nothing to add to `package.json` for it;
its glow-card/gradient-border idiom is instead hand-built directly in
`components/GenreShowcase.tsx`.

### Brand continuity with ARCHITECTURE.md's trace artifact

Rather than invent a new palette and type pairing from scratch, this slice
deliberately reused the one already established for the Slice 8 interactive
agent-trace artifact: the same amber accent (`#f0a63a` dark / `#a8650f`
light), the same Archivo + IBM Plex Mono pairing. The alternative — a
distinct look for the live app versus the docs' interactive artifact — would
have made the project read as two different projects wearing one name. The
same reasoning extended into the product itself: `components/TraceSteps.tsx`
re-renders the streamed progress events as a node-by-node stepper using the
graph's real node names (router → retrieve_schema → agent → execute_tools →
build_chart_spec), the same visual grammar as the ARCHITECTURE.md diagram,
instead of Slice 6's flat scrolling text log. The trace concept isn't just
documentation anymore — it's now a real UI element a user watches live.

### Genre identity: real counts, not invented ones, and why 8 not 12

"Illustrated identity per genre" needed an actual genre list before anything
else. SteamSpy's `genre` field turned out to be free-text and comma-joined
(`"Action, Adventure, RPG"`, not an enum) — queried the real 200-game
catalog directly (`data/db/games.duckdb`), split every row's genre string on
comma, and counted tokens rather than guessing a plausible-looking list.
Real result, most common first: Action 148, Adventure 75, Indie 67, Free To
Play 52, RPG 50, Simulation 41, Massively Multiplayer 38, Strategy 33,
Casual 24, Early Access 13, Sports 13, Racing 7 (plus a handful of one-off
non-game tags like "Photo Editing" — noise from a few mislabeled catalog
entries).

Cut this to 8 for `lib/genres.ts`: "Early Access" (a release status, not a
genre) and "Free To Play" (a pricing model) were excluded on category
grounds, and the dataviz skill's categorical-palette rule is a hard 8-hue
cap regardless — a 9th series never gets a generated hue, it folds into
"Other." That cap happened to land exactly on a clean real cutoff (Casual at
24 vs. the excluded pair's actual genre-adjacent neighbors Sports/Racing at
13/7), so nothing had to be forced.

Colors reuse the dataviz skill's already-validated default 8-slot
categorical palette (`references/palette.md`) rather than deriving a new
one — assigned in the genres' real prevalence order (Action → slot 1 blue,
… Casual → slot 8 red), which preserves the CVD-safety guarantee that was
validated for this exact hue *sequence* (re-ordering which hue means which
genre is fine; what the validator actually checked was adjacency within
this sequence). Re-ran `validate_palette.js` against this app's own light/
dark chrome surfaces (`#faf8f4`/`#141310`, not the skill's reference
surfaces) rather than assuming the original validation still holds on a
different ground — both pass every check; light mode WARNs on raw contrast
for 3 of the 8 hues (aqua/yellow/magenta), which the skill flags as needing
a relief channel — satisfied here since every genre card always carries a
matching icon and text label, so identity is never color-alone regardless.
One caveat logged honestly: the categorical validator's "adjacent pairs"
model is a linear sequence (bars/lines), and this palette is displayed in a
2D grid, where a card has up to 4 visual neighbors, not 2. Didn't re-derive
for grid-adjacency specifically — the icon+label pairing already makes
color non-load-bearing, which covers the gap.

Eight hand-authored line-art SVG glyphs (`components/GenreIcon.tsx`) — a
crosshair, compass, pixel-heart, gem, gear-spokes, network nodes, a 3×3
grid, a smiley — rather than pulling in an icon library for 8 shapes.

Genre cards aren't decorative: clicking one calls the same `ask()` path as
the Slice 6 example-question chips, with a genre-specific real question
(`lib/genres.ts`'s `question` field) that the existing agent can already
answer with zero backend changes — same reasoning Slice 7 leaned on for
player-count questions ("meant to grow" schema, no new code needed).

### Accessibility: `MotionConfig reducedMotion="user"`, once

Rather than checking `prefers-reduced-motion` in every animated component,
`components/MotionProvider.tsx` wraps the whole app in a single
`<MotionConfig reducedMotion="user">`. Motion's own reduced-motion mode
keeps opacity/color transitions but makes positional animation (the hero's
stagger-in, card lift, trace-dot scale) instant — one line, whole-app
coverage.

### Verification, and a real bug found in the process

Built the whole slice, then drove it in an actual browser (Playwright) —
not just visual screenshots of static markup, but a real interaction: click
a genre card, watch the trace stepper animate through real streamed
progress events, wait for either a result or a failure. Checked light and
dark themes, and a hover state (the card's radial glow).

That last check surfaced a real, pre-existing **backend** bug, unrelated to
this slice's own code: `POST /ask/stream` crashes the whole Python process
—not a Python exception with a traceback, a hard native fault
(`OPENSSL_Uplink(...): no OPENSSL_Applink` printed to stderr, then the
process exits) — reproducibly, on the first request that does real work.
`/health` (no outbound network call) works fine every time; the crash
happens exactly when the agent would make its first real HTTPS call (Groq).
Working hypothesis, not yet confirmed: `truststore.inject_into_ssl()` (added
back in the pyproject.toml/uv migration, to route around Avast's TLS
interception via the OS trust store) patches Python's global `ssl` module
in a way that collides with another native extension's own statically
linked OpenSSL the first time a real TLS handshake actually happens — the
same family of Windows TLS issue this project has already hit twice before
(`uv sync`/`uv lock`'s `UnknownIssuer` errors), just triggered from inside
the running app instead of from `uv`. Not chased further here: it's a
backend runtime issue, out of scope for a frontend-visual-polish slice, and
guessing at a fix without reproducing it outside this one environment risked
breaking the ingestion/eval paths that already depend on `truststore`/
`native-tls`. What *was* verified: the frontend's own handling of a dropped
connection is correct — `lib/api.ts`'s `fetch` rejects, `page.tsx`'s catch
block sets the existing "Couldn't reach the backend" error state, no crash,
no stuck loading spinner.

### Open questions (new)

- **The `/ask/stream` native crash needs real investigation** — likely
  `truststore` vs. some other native extension's bundled OpenSSL on
  Windows, per the hypothesis above, but unconfirmed. Next step if
  picked up: reproduce with `MODEL_PROVIDER=ollama` (no outbound HTTPS at
  all) to test whether the crash is specifically tied to the first real
  TLS handshake, then bisect which native extension collides with
  `truststore`'s patched `ssl` module.
- **Grid-adjacency CVD validation for the genre palette** — validated as a
  linear sequence per the dataviz skill's method; a true 2D-grid adjacency
  check would need extending the validator's pairlist logic, not attempted
  here since the icon+label pairing already covers the accessibility gap.

---

## Slice 9b — Retro redesign, real forecasting, dynamic genre stats

**Date:** 2026-08-25

The user tried Slice 9's frontend, and it worked (a real Groq round trip
rendered correctly, screenshots included), but the reaction was blunt: it
"feels like an AI slop website." Fair — re-reading it, the first pass had
drifted into exactly the look the artifact-design skill's cliché list warns
about: soft rounded-xl everything, muted warm neutrals, safe spacing. Good
engineering, forgettable design. Three follow-on requests arrived together:
make it genuinely distinctive ("retro"), build the forecast route for real,
and stop hardcoding the genre-showcase counts.

### Picking a retro lane, not "retro" in general

"Retro" spans unrelated worlds — asked the user to choose among three
concrete directions (80s arcade/neon, 90s terminal/phosphor, Y2K
retro-futurism) rather than guess, since a full visual identity is expensive
to redo twice. Landed on 80s arcade/neon. That decision drove real,
falsifiable choices, not just a vibe:
- Sharp corners + thick borders everywhere a panel/console appears (cabinet
  bezel), contrasted with round pill buttons for actual clickable controls
  (cabinet joystick buttons) — the contrast is the point, not an oversight.
- Four typefaces, each doing exactly one job, is a genuine departure from
  the "one display + one body" pairing structure `artifact-design` normally
  recommends: Archivo (body/UI, unchanged), IBM Plex Mono (data/code,
  unchanged), **Monoton** (the hero headline, *only* the hero headline — a
  neon-tube marquee face, illegible at paragraph length by design, which is
  exactly why it's confined to four words), **Press Start 2P** (pixel
  labels — section eyebrows, route/cached badges, the trace stepper's node
  labels; same illegibility-at-length constraint, same confinement).
- The marquee chase-light animated border (`.marquee-border` in
  globals.css — a rotating `conic-gradient` masked to a ring via
  `@property --marquee-angle`) went on exactly one element, the ask console.
  Considered putting it on the result panel too and didn't — one orchestrated
  motion moment reads as a choice; two competing ones read as decoration.
- Grounds got realigned to the *exact* hex values ARCHITECTURE.md's
  agent-trace artifact already used (`#0d1014` dark / `#f6f4f0` light) rather
  than the close-but-not-identical approximation Slice 9 shipped
  (`#141310`/`#faf8f4`) — the user's second screenshot in this conversation
  was literally that artifact's graph, used as the reference for "this is
  the level of polish I want," so tightening brand continuity to match it
  exactly was the correct read of that signal, not a coincidence to ignore.

### Forecast: honesty moved from the router into the tool

Slice 3/4 explicitly deferred forecasting with a hardcoded router→
terminal-node "not supported yet." That's gone now: `forecast` flows through
the identical retrieve_schema → agent → execute_tools loop as lookup/
analysis (see ARCHITECTURE.md's updated graph), with `run_forecast`
(`src/tools/forecast_tool.py`) bound alongside `run_sql`. The interesting
design decision wasn't the linear regression (scipy `linregress`, nothing
exotic) — it was where the "do we actually have enough data" honesty check
lives. It does NOT live in the router (classify forecast questions as
forecast regardless of whether data exists — the router's job is
understanding the question, not knowing the DB's current state) and does
NOT live in a route-level gate (a fixed "not supported" block would make the
feature permanently disabled even once real history accumulates). It lives
*inside the tool*: `execute_run_forecast` checks the actual distinct
snapshot count for whatever query the LLM wrote, and returns a structured
`insufficient_history` result instead of fitting a line through one point.
This means the feature **self-upgrades**: the moment the Slice 7 poller
lands a second real snapshot for some game, that game's forecast questions
start returning real projections, with zero code changes — verified this is
architecturally true by unit-testing `_forecast()` directly against
constructed multi-point data (a real 6-point rising series, both a
near-horizon and a deliberately-absurd 365-day-out horizon), not just
against the real (currently single-snapshot) DB.

Also added a `low_confidence` flag, separate from `insufficient_history`:
even with ≥2 points, projecting further ahead than the *observed* span is
extrapolation past what the data can support, and <5 points is thin enough
that a line captures noise as easily as trend. Both conditions are checked
independently and their reasons are returned as a list, not a boolean —
the system prompt (`FORECAST_TOOL_GUIDANCE` in prompts.py) instructs the
model to always surface these reasons in prose rather than stating a
number with false confidence. Verified end-to-end with a real Groq call
against "How many players will Counter-Strike have next year?" (the exact
phrase the router/prompts docstrings use as their example, and one of the 4
default example questions in the frontend) — the agent correctly reported
insufficient history AND, on its own initiative, fell back to a real
`run_sql` query for CS:GO's `peak_ccu` to give a useful answer instead of a
bare refusal. That fallback behavior wasn't prompted for explicitly; it fell
out of binding `[run_sql, run_forecast]` together for the forecast route
(the same "give it more than one tool and let it decide" pattern
`analysis`'s `[run_sql, run_stats]` already established in Slice 4).

### Dynamic genre counts: what the user actually flagged

Mid-session interjection: "I dont want just 200 data timestamp, I want the
retrieval of the data to be dynamic." Read literally this is about
`player_counts`, but in context (right after seeing the genre showcase) it
was about `lib/genres.ts` — Slice 9 baked the 8 genre labels/counts in as a
TypeScript literal, computed once by hand against a local export. That's
exactly the kind of frozen snapshot the project's `refresh_catalog.yml`
(weekly re-ingestion) would silently invalidate. Fixed by adding
`GET /genres` (`src/db/genre_stats.py`) — the same split-comma-and-count
logic, now running at request time against the live `games` table — and
having `GenreShowcase.tsx` fetch it on mount instead of importing a
constant. Went further than just re-fetching the *counts*: which 8 labels
even make the top-8 is now live too, since the real top-8 could shift as
the catalog grows. That meant `lib/genres.ts` had to change shape — it's no
longer a list of genres, it's curation metadata (icon id, a nicer example
question) keyed by label, with a generic fallback (`GenreIcon`'s new
`Generic` glyph, a templated "What are the 5 highest-rated {label} games?"
question) for any label outside the curated set. Deliberately did NOT try
to curate icons for every SteamSpy tag the catalog could ever produce —
Sports and Racing got real hand-drawn icons since they're plausible top-8
contenders; the long tail (the occasional mislabeled non-game entry
producing a tag like "Photo Editing") gets the generic fallback and that's
fine, it's meant to.

This turned `genre_stats.py` into the first read path in the whole system
that touches the DB *without* going through `connection.py`'s guard —
worth being explicit about why that's correct, not an oversight: the guard
exists to constrain **LLM-generated** SQL. `genre_stats.py` runs one fixed,
hand-written query with no model or user input anywhere in it. Routing it
through `validate_select_only` would add a dependency for zero safety
benefit — there's nothing adversarial to guard against here.

### A real bug, found by accident, that had nothing to do with any of this

Tried to verify the forecast feature live and hit the exact `/ask/stream`
crash flagged (but not investigated) at the end of Slice 9 — `OPENSSL_Uplink
(...): no OPENSSL_Applink`, killing the whole Python process, no traceback.
Slice 9's DOCEXP entry guessed this was `truststore`'s `ssl` patch colliding
with some other native extension's bundled OpenSSL. **That hypothesis was
wrong**, and worth recording as wrong rather than quietly dropped, per this
file's own habit of correcting itself in the open (see the Slice 4 group-
mislabeling entry).

Isolated it properly this time, one layer at a time, in the actual venv:
1. A **plain `requests.get()`** to a real HTTPS endpoint, zero project code
   imported — crashed identically. Ruled out truststore, ruled out Groq's
   SDK, ruled out LangChain/LangGraph entirely; this was never an agent-code
   bug.
2. **Raw stdlib `ssl.wrap_socket()`**, no `requests`/`urllib3` either —
   crashed identically. Ruled out the requests/urllib3 layer too. This is a
   fault in the Python installation's own TLS stack, full stop.
3. The **already-installed Microsoft Store Python 3.12** on the same
   machine — same real network, same Avast, same everything else — did a
   real TLS handshake to the same host with zero issue. This is what ruled
   out Avast as the cause of *this specific crash* (Avast's TLS interception
   is real and is exactly why `truststore` exists at all — but it produces a
   catchable `CERTIFICATE_VERIFY_FAILED`, not a process-killing native
   fault, and this system Python hit neither).
4. A **uv-managed Python 3.12.13** (`uv run --python 3.12`) — also clean.
   At this point the only variable left was the interpreter build itself:
   the project's `.venv` was on uv's default pick, **3.14.2**, uv's newest
   available standalone Windows build at the time. Python 3.14 had only
   just been released; a rough edge in a brand-new platform-specific
   standalone build was, by this point, the only hypothesis still standing.

Fixed by pinning `.python-version` to `3.12` and rebuilding `.venv` (`rm -rf
.venv && uv sync --extra agent`) — `requires-python = ">=3.12"` already
permitted this, so no dependency constraint needed to change. Re-ran the
same plain-`requests` probe on the rebuilt venv: it now failed with the
*expected*, *already-understood*, *already-solved* Avast error
(`CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate`) — and
then succeeded cleanly once `src.config` (which calls
`truststore.inject_into_ssl()` at import time) was imported first. That's
the tell that this really was two separate, unrelated issues stacked on top
of each other: a genuine `python-build-standalone` 3.14.2 Windows bug (fixed
by not using that build), sitting on top of the long-standing, already-
correctly-handled Avast TLS interception (fixed by `truststore`, same as
every prior occurrence in this project). Confirmed fixed against a real
Groq call afterward — see the forecast section above.

The methodological point worth keeping: the fix came from isolating variables
one at a time against the *real* environment (this venv, this network, this
Avast install) rather than pattern-matching to "we've seen a TLS error
before, it's probably the same cause" — the previous entry's guess did
exactly that pattern-match and was wrong.

### Open questions (new)

- **`.python-version` pins 3.12, not a specific patch version.** uv will
  still pick up new 3.12.x patch releases as they're published. Reasonable
  for now; revisit if a similar issue ever shows up on a specific patch.
- **Should this project's CI/deployment pin Python the same way?** The
  `Dockerfile` doesn't currently specify a Python version explicitly at all
  (relies on whatever `uv sync` resolves inside the container image) — worth
  checking it doesn't silently pick up a fresh, potentially-buggy standalone
  build the same way local dev just did.
- **The result panel's answer text renders literal `**markdown**`
  asterisks** — noticed during this slice's live screenshots (pre-existing,
  not introduced here: `<p>{result.answer}</p>` has never parsed markdown).
  Small, real, not fixed here — out of scope for a redesign+forecast slice.
  Fixed next in Slice 9c.

---

## Slice 9c — Markdown, real genre browsing, Anime.js background

**Date:** 2026-08-25

Three follow-ons from actually using Slice 9b: the markdown bug flagged (but
correctly left unfixed, as out of scope) at the end of that entry, the
genre showcase's click behavior, and a request to use Anime.js specifically
for background motion.

### Markdown: `react-markdown` over hand-rolling it

Considered a small hand-written `**bold**`/`* item` regex parser first —
consistent with this project's usual "no dependency for something this
small" instinct (the SSE parsing in `lib/api.ts` is hand-rolled for exactly
that reason). Went with `react-markdown` instead once the actual failure
mode was reconsidered: the agent's answers are real LLM prose, not a fixed
template, so what shows up (bold, bullet or numbered lists, occasional
inline code) is whatever GPT-OSS decided to write — a hand parser would need
to cover CommonMark's real edge cases (nested lists, escaped characters,
mixed list markers) to not just move the bug rather than fix it, at which
point it's reimplementing a markdown parser, badly, instead of using the
industry-standard one. `components/Markdown.tsx` wraps it with an explicit
`components` map — every element (`p`, `strong`, `ul`/`li`, `code`, `a`) is
styled to this app's own tokens by hand, not a generic `@tailwindcss/
typography` "prose" class, so the rendered markdown looks like it belongs
to this app specifically rather than to a plugin's default theme.

### Genre cards: browsing, not asking

Slice 9 made a genre card fire a curated LLM question. Explicit correction
this round: "when we click on it, we should display the games." This is a
better design independent of being asked for — clicking a card to *browse*
what's actually in that genre is a faster, more expected interaction than
clicking a card to *ask an AI about* that genre, and it doesn't cost a Groq
round trip to satisfy. `GET /games` (`get_games_by_genre` in
`src/db/genre_stats.py`, alongside `get_genre_counts`) is a second
deterministic, no-LLM, no-guard endpoint for the same reason the first one
is: it's one fixed query with a parameterized genre argument, not
LLM-generated SQL, so `connection.py`'s guard has nothing to add. Matches on
the comma-split token (case-insensitive), not a raw `ILIKE '%label%'`
substring — same reasoning `get_genre_counts()` already established: a
substring match on the whole free-text field can't distinguish a real match
from an accidental one where the label happens to be a substring of a
different, unrelated tag.

The LLM-question path didn't disappear — a card's expanded panel has a
secondary "ask the agent about {genre} →" link that calls the same
`onPick` the old click behavior used, so both interactions coexist:
fast/deterministic browsing as the primary action, the agent still one
click away for anyone who wants a synthesized answer instead of a raw list.

One real implementation snag, not a design decision: the new-ish
`react-hooks/set-state-in-effect` ESLint rule flagged calling `setGames(null)`/
`setGamesLoading(true)` synchronously in the effect body that runs the
fetch. Fixed by moving those two resets into the click handler itself
(`toggle()`) — the effect now only sets state from the async fetch's
resolution (`.then`/`.catch`/`.finally`), which is what the rule is
actually asking for: an effect should react to an external system's result,
not synchronously mutate state itself the moment it runs.

### Anime.js: one exception, scoped on purpose

The user asked for it by name again, specifically for background animation,
after Slice 9's consolidation onto Motion alone (partly *because* the
original ask listed Anime.js as one of four overlapping libraries for
general UI animation). This isn't reopening that call: `components/
RetroBackground.tsx` is a synthwave grid-horizon-plus-drifting-motes loop
with **no React state involved at all** — nothing it animates is derived
from or feeds back into a component's props/state. Motion's whole value
proposition (`variants`, `AnimatePresence`, gesture props tied to render)
doesn't apply to a background that never needs to know anything about the
React tree. Anime.js's imperative, timeline-first API — grab a DOM/SVG ref,
animate it, let it run — is a better fit for exactly that job, and using it
there isn't redundant with Motion's job anywhere else in the app. Kept
strictly to this one file; nothing else in the app imports it.

Implementation notes, since Anime.js v4 is a genuinely different API from
the v3 most people remember (`anime({targets, ...})` → named exports
`animate(targets, params)`, `easing` → `ease`, modular sub-path imports)
— introspected the installed package's actual `.d.ts` files rather than
trusting memorized v3 API shape, same discipline as the MCP SDK version
drift in Slice 8. One real design choice inside it: the scrolling grid is
NOT an animated SVG `<pattern>` (the first draft used one) — CSS `transform`
support on `<pattern>` elements is inconsistent across browsers since
patterns aren't normal rendered/laid-out elements. Switched to animating a
plain `<g>` of explicit `<line>` elements instead (universally reliable),
sized with two extra rows past both edges of the visible band so a
one-row-height loop reads as continuous with no visible seam at the wrap.

### Open questions (new)

- **No table/task-list markdown styling** — `react-markdown`'s default
  CommonMark support covers everything seen in real answers so far (bold,
  lists, occasional code); GFM extras (tables, strikethrough) aren't wired
  up (`remark-gfm` isn't installed) since no real answer has needed them
  yet. Add it if/when a stats answer actually wants a table.
- **The games leaderboard always shows exactly what `get_games_by_genre`
  returns (top 8 by review score, then peak CCU)** — no sort/filter control
  in the UI yet. Fine for a browsing entry point; would need one if this
  panel grows into something people spend real time in.

---

## Slice 9d — One committed scene, not a subtle texture

**Date:** 2026-08-25

The reaction to Slice 9c's ambient background: "I don't like the black or
white," with a specific reference image — a magenta grid horizon under a
glowing sun, mountains in silhouette. Not "more retro texture," a
correction: the earlier treatment was a faint decoration on top of a
neutral near-black/near-white page; what was actually wanted is that scene
*as the page itself*.

### Dropping dual-theme for the chrome tokens, on purpose

This is worth being explicit about since it's a real reversal of a
discipline this project followed carefully through Slices 6-9c: brand
chrome (`--background`, `--surface`, `--foreground`, etc.) no longer has a
light/dark split. One synthwave-night palette, always. Two reasons this is
the right call here rather than a corner cut: (1) the reference is
inherently a night scene — a "light mode" synthwave horizon isn't a
lighter version of the same thing, it's a different image, and diluting a
specific, deliberate reference into two lesser variants would serve
neither; (2) the `artifact-design` skill explicitly carves out exactly this
case ("a design that deliberately commits to one visual world... may stay
single-theme"). The genre categorical palette and `.viz-root` chart tokens
both collapsed to their single already-dark-tuned values too, for the same
reason — every surface in the app is dark-glass now regardless of OS
theme, so keeping a light variant of hues tuned for a light surface that no
longer exists would be dead code, not a real fallback.

`--accent` didn't change value (`#ffc857`, close to the prior `#f0a63a`) —
it's still the same warm-gold thread running through the trace artifact and
the rest of the app, and it happens to double as "the sun's color" in the
new scene without any adjustment needed. One brand color, two coincidentally
compatible contexts.

### The scene itself

`components/RetroBackground.tsx` (rewritten, not extended) draws sky
(linear gradient, 5 stops), a sun (radial gradient circle, masked with a
few horizontal black bars near its base for the classic "striped retro
sun" look), two layers of low-poly mountain silhouettes (`ridge()` — a
small deterministic sine-wobble generator, not hand-typed path data,
consistent with the diagramming discipline's "avoid long decorative path
data"), and a neon grid: static converging verticals fanned from a single
vanishing point (the "endless road" half of the perspective) plus the
previously-built animated horizontal scan-lines (recolored magenta,
boosted opacity, Anime.js-driven scroll unchanged in mechanism from Slice
9c). Panels got a `.glass-panel` utility (translucent surface +
`backdrop-filter: blur`) so they read as chrome floating over the scene,
not boxes painted on top of it.

### Cartridges, and a real rendering bug found building them

"Some cartridges to be the choices... like the old Game Boy or DS
cartridges" — genre cards became `components/GenreCartridge.tsx`: a
chamfered-corner silhouette (one shape family for all 8 genres, not
alternating Game Boy/DS shapes — cohesion over literal variety), a
label-sticker window holding the existing `GenreIcon` glyph, and a
connector-notch ridge at the bottom. Hover lifts and slightly rotates the
cartridge (Motion spring, `whileHover`) for a physical "pop out" read.

First draft used `clip-path: polygon(...)` alone on the glass-panel div to
cut the chamfer. Screenshotted it to verify (the discipline that's caught
every other visual bug this project has shipped) and the corner looked
perfectly square — no chamfer visible anywhere, on any of the 8 cartridges.
Root cause, once actually checked (`getComputedStyle` confirmed the
clip-path value WAS applied correctly): `clip-path` genuinely removes the
pixels outside the polygon, but it doesn't paint anything new along the
edge it creates — the `border-2` on that div still only draws along the
*original* rectangular box edges, so where the clip line cuts through,
there's no stroke at all, just a bare edge revealing whatever's behind it.
Since what's behind it (the scene, at the point genre cards sit) is a
similarly dark color to the panel's own near-black glass, the cut was real
but had ~zero visual contrast — geometrically correct, invisible in
practice. Fixed by overlaying a second, stroke-only SVG `<polygon>` (same
points, `fill="none"`) directly on top — that's what actually draws a
visible line along the diagonal, since an SVG stroke traces its shape's
full boundary regardless of what a sibling element's CSS clip did.
General lesson worth keeping: `clip-path` clips content, it does not
imply an outline — anything that needs the cut *edge itself* to be
visible needs something else to draw it.

### Addendum: font swap, and actually centering the sun

Two immediate follow-ons once this was live: the body font still read as a
generic modern grotesque next to Monoton/Press Start 2P/Plex Mono, and the
sun sat too high — mostly hidden behind the hero copy rather than being a
real focal point.

Swapped `--font-display` from Archivo to **Chakra Petch** — full weight
range (so it still works for both body copy and semibold labels, unlike
Audiowide/Orbitron which are single-weight display faces that get
illegible at paragraph size), with a squared-off, slightly-angular
character that actually reads as retro-computer rather than a neutral
grotesque wearing a retro palette.

Centering the sun took two tries. First attempt: changed the SVG's
`preserveAspectRatio` from `xMidYMax slice` (bottom-anchored — where the
horizon/sun end up depends on how much the viewport's aspect ratio
overflows vertically, which is what was pushing the sun up out of view)
to `xMidYMid slice`, and grew the viewBox from `800x600` to `800x900` with
the horizon fixed at the exact vertical middle (y=450) — this makes the
horizon land at the vertical center of *any* viewport predictably, not
wherever the old aspect-ratio math happened to put it. Verified the math
holds by hand for a few real viewport ratios before trusting it (a
1280×1100 window: scale is width-driven at 1.6×, the visible vertical crop
window maps back to a horizon position of exactly 50% — confirmed, not
assumed) rather than just eyeballing one screenshot and hoping it
generalizes to other window sizes. Also extended the ground/grid drawing
to y=1000 (past the 900-tall viewBox) so no real aspect ratio produces a
visible gap under the grid — checked this explicitly against a tall/narrow
900×1400 viewport, the shape most likely to expose one.

That first attempt centered the sun correctly but made it too large and
too bright exactly where the hero paragraph lives — a real legibility
regression, caught by screenshotting before calling it done (the same
discipline that caught the invisible cartridge chamfer earlier in this
slice). Fixed two ways together, not by picking one: shrank the sun
(r 168→132) and biased it down slightly relative to the horizon so its
brightest band sits mostly above the text column instead of behind it, and
gave the hero paragraph a dark text-shadow plus switched it from the muted
lavender tone to full foreground-white — belt-and-suspenders, since exact
sun geometry will never guarantee zero overlap at every viewport size, but
shadowed white text stays readable against anything behind it regardless.

### Open questions (new)

- **No light-mode fallback exists anymore for anyone who'd genuinely prefer
  one** — a deliberate scope choice (see above), not an oversight, but
  worth revisiting if that preference ever comes up for real.
- **Mobile/narrow-viewport rendering of the scene and cartridges wasn't
  separately verified this round** — desktop (1280px) was checked
  thoroughly (hover, selection, the leaderboard panel, no console errors);
  the responsive grid classes themselves are unchanged from Slice 9, so
  behavior should carry over, but that's inference, not a check.

---

## Slice 9e — The markdown bug's real cause, and actually checking mobile

**Date:** 2026-08-25

Two follow-ons, and both are examples of the same lesson: an open question
flagged and left unfixed will eventually be the thing that breaks.

### The markdown bug wasn't a rendering bug

Slice 9c added `react-markdown` and it worked — verified live with `<strong>`
count assertions and everything. So when the user reported the exact same
raw-asterisks symptom afterward, the reflexive assumption would be "the fix
didn't actually ship" or "there's a renderer edge case." Checked the actual
API response first instead of guessing: the answer string itself was
`"...* **Mean price – Indie games:** ≈$15.50 * **Mean price..."` — all one
physical line, bullets separated by inline `*` with no newline anywhere
between them. That is not valid CommonMark. No markdown renderer, correctly
implemented, turns that into a list — the asterisks are ambiguous emphasis
delimiters at best, literal characters at worst, and `react-markdown` was
doing exactly the right thing with genuinely malformed input. The Slice 9c
fix was real and still works (confirmed again this round); the bug was one
level upstream, in what the model was writing, not in what parsed it.

Fixed by adding an explicit formatting section to `SYSTEM_PROMPT_TEMPLATE`
(`src/agent/prompts.py`) — spelling out, as literal instruction rather than
implication, that the answer is rendered as markdown, that ≥3 related
numbers should become a real GFM table (header row, `|---|---|` separator,
data rows), and that a chained one-line `* label: value * label: value`
run is explicitly called out as *not valid* and *not to be used*. Paired
with a frontend change either way: added `remark-gfm` to `react-markdown`
so that when the model does emit a real table, it renders as a real
`<table>` (styled in `Markdown.tsx` to match the rest of the app — pixel-
font gold headers, monospace data cells) instead of raw pipes and dashes.
Neither fix alone would have been enough: prompt-only leaves a client that
can't render a table if the model gets the syntax right; renderer-only
does nothing about a model that never produces valid list/table syntax in
the first place. Verified against the literal question that broke
originally (Indie vs. other games price comparison) — real 2-row table,
zero raw `**`, zero raw `----`, confirmed as an actual `<table>` element in
a live browser, not just well-formed markdown in the API response.

### Actually testing mobile, instead of inferring it

Both the Slice 9c and Slice 9d entries logged "mobile wasn't separately
verified, but the responsive classes are unchanged so it should be fine" as
an open question — a reasonable-sounding inference that turned out to be
wrong. Ran Playwright with real device emulation (iPhone 14, Pixel 7) for
the first time on this redesign and found a genuine bug immediately: the
genre showcase's section header (`[ OR EXPLORE BY GENRE ]` next to "live
from the catalog") had `justify-between` with no `flex-wrap`. Every other
`justify-between` row in the app already had `flex-wrap` (added when each
of those was originally built and visually checked) — this one line was
just missed, and nothing caught it because desktop viewports never got
narrow enough to expose it. Fixed by adding `flex-wrap` + explicit gap,
same pattern as its siblings. The methodological point: "the classes didn't
change" is not the same claim as "the layout still works" — narrower
viewports can expose a latent bug in code that was never touched, if it was
never actually tested at that width to begin with.

### Dropping the Expo mobile client

The user's call, stated directly: a native app isn't worth it for what this
is — one tool, one page's worth of functionality, and doubling the UI
surface (Slice 9's whole visual system would need a second, React Native
implementation) for what a responsive browser tab already covers once it's
actually been verified to work on a phone-sized screen. Moved Slice 10 from
"Expo mobile client" to a mobile-web-polish-plus-deployment slice instead;
the Expo entry moved to Dropped in PLAN.md, next to the earlier Gemini
decision — same shape of decision (a planned-for-later item, reconsidered
once the actual cost/benefit was concrete instead of hypothetical).

### Addendum: 200 was a config default, not a SteamSpy limit

The user asked directly whether 200 games was all SteamSpy would give —
worth checking the real ceiling rather than assuming. It wasn't a limit at
all: `ingest_game_count = 200` in `src/config.py` was just the number
`ingest.py` happened to slice off SteamSpy's bulk `all` listing.
`get_all_page(page=0)` already returns ~1000 games (SteamSpy's own
per-page size, sorted by owners descending) — `ingest.py` was only ever
asking for the first 200 of those. Getting more right now is a config
change, not a code change; getting past ~1000 would be a real one
(`ingest.py` only fetches page 0 — looping over page 1, 2, ... isn't built).

Bumped the default to 1000 everywhere it's declared (`src/config.py`,
`.env.example`, the real `.env`) and re-ran ingestion. Deliberately did
**not** bump the `Dockerfile`'s build-time `ARG INGEST_GAME_COUNT` default
— that ingestion happens at Docker build time on whatever host deploys
this, and rate-limited to ~1 req/sec, 1000 games adds real minutes to
every future build. Left it at 200 (fast builds by default) with a
comment already in place noting it's overridable via `--build-arg` for
anyone who wants the full 1000 in a deployed instance and is fine trading
build speed for it.

### Open questions (new)

- **Mobile design is verified-not-broken, not verified-well-designed.**
  Slice 9e confirmed nothing overlaps/overflows; it didn't do a real design
  pass for touch targets, cartridge grid density at 2 columns, or
  leaderboard table readability at narrow widths. That's explicitly Slice
  10's job now, not assumed done.
- **Deployment platform: sticking with the Slice 6 decision (Vercel +
  Render/Fly.io) unless a real reason to reconsider comes up.** The user
  asked about alternatives (not Streamlit — correctly, this isn't a
  Streamlit app; floated Replit). Worth a documented compare-and-decide
  pass in Slice 10 rather than assuming the two-year-old-in-project-time
  Slice 6 reasoning still automatically wins, even though it's still
  probably right (this stack's real footprint — DuckDB, fastembed's ONNX
  model, scipy, multi-step LLM calls — doesn't fit a lightweight
  always-on-free-tier host well, which is the same reason Vercel's own
  Python functions were ruled out in Slice 6).

---

## Slice 9f — More data, and taste applied concretely instead of by feel

**Date:** 2026-08-26

Two follow-ons: confirming 200 games was a config default not a real
ceiling (see PLAN.md's Slice 9f entry for the mechanics — SteamSpy's bulk
page already holds ~1000, `ingest.py` just wasn't asking for that many),
and a design request that named a specific reference (Emil Kowalski's
public writing on interaction craft) rather than "make it nicer."

### Grounding "taste" in something checkable

Asked to apply Kowalski-style taste without inventing a fictional "skill"
for it — his actual published material is real and specific enough to work
from directly. Fetched his site and "7 Practical Animation Tips" rather
than working from vague memory of "that designer with the nice toasts."
Audited this app's existing motion against each of the 7 concretely:

- **Button press scale (0.97, `:active`)** — the Ask button and genre
  cartridges already had tap feedback; the example-question chips didn't.
  Real, findable gap once actually checked against a checklist instead of
  a general "does this feel okay" pass. Fixed, and unified every
  interactive element's press scale to the same 0.97 — one consistent
  value reads as deliberate, three slightly different ones read as
  accidental.
- **Avoid animating from `scale(0)`** — audited every `initial`/`animate`
  pair in the app; none do. No change needed, but worth having actually
  checked rather than assumed.
- **`ease-out`, not `ease-in`, for entering/exiting** — the hero stagger
  and card entrances already use a custom ease-out-heavy cubic-bezier
  (`[0.16, 1, 0.3, 1]`), applied symmetrically to both enter and exit
  transitions, which is exactly what the tip recommends (ease-out for
  both, not ease-in for exits). Already correct.
- **Keep it fast, <300ms for frequent interactions** — this app's
  interactive elements (button taps, cartridge selection) are already
  spring-based and settle quickly; explicitly set the new chip
  press-transition to 150ms rather than leaving it at Motion's spring
  default, for consistency with the Ask button.
- **Blur for rough transitions** — genuinely new. Added
  `blur(4px)→blur(0px)` to both the progress-panel and result-panel
  `AnimatePresence` transitions, matching Kowalski's specific "underrated"
  recommendation for masking the seam when one piece of UI replaces
  another.
- **Origin-aware transforms / skip delays on repeat tooltips** — don't
  apply here (no popovers-from-a-trigger-point or tooltip sequences in
  this app); noted as checked-and-not-applicable rather than silently
  skipped.

The point of fetching the actual source first: three of the seven tips
turned out to already be satisfied by decisions made earlier in this
project for unrelated reasons (the ease-out curve was chosen in Slice 9
for how it looked, not because it matched a specific external principle) —
worth knowing that's true, rather than assuming a "craft pass" always
means new changes everywhere.

### Open questions (new)

- **No literal "taste" or design-review skill exists for this project** —
  applied the specific external reference material directly this round;
  if this kind of audit becomes routine, a real project skill capturing
  "the checklist to run" would be the next step, not this ad hoc version.

---

## Slice 9g — Retro didn't work; a full, honest rebuild

**Date:** 2026-08-26

The direct feedback: "change the landpage completely, I want it to be
better, more professional and not look like AI slop." Worth being honest
about what this means for the previous three slices (9, 9b, 9c, 9d): the
synthwave-arcade direction, however carefully crafted at each step (the
cartridge chamfer bug, the sun-recentering math, the Kowalski animation
audit — all real, all correct engineering), was the wrong *concept*, not a
concept that needed more polish. Worth naming why plainly, since it's a
real lesson: a magenta grid horizon under a neon sun plus a pixel font is,
at this point, a recognizable template trope — codepen demos, "80s retro"
site-builder themes, and a large fraction of AI-generated landing pages all
converge on some version of it. Execution quality doesn't rescue a concept
that reads as generic before anyone evaluates the execution. This is
exactly the failure mode `artifact-design`'s own "avoid AI-generated
design" cliché list is warning about, just a cliché the list doesn't
happen to name — the list isn't exhaustive, the underlying test
("does this read as chosen for this subject, or as decoration pulled from
a shared aesthetic pool?") is what actually matters.

### Grounding the new direction in something real, twice

Two things were checked directly rather than assumed, same discipline as
the Kowalski animation pass: fetched linear.app itself (got a fairly
generic AI-summarized read back — the page is heavily client-rendered, so
the fetch didn't surface much concrete detail) and leaned on directly-
verifiable specifics instead of the vague summary: near-black grounds,
hairline borders, restrained single-accent color, real typographic scale
carrying the hero instead of a display face. Chose Geist over literally
matching Linear's font — distinct enough not to be a copy, same quality
tier and the same "serious dev tool" association (it's Vercel's own font),
and confirmed it was actually in the next/font/google catalog before
committing to it rather than assuming.

### Why real 3D, not a CSS approximation

The ask was specific: "3D objects of gaming icons." CSS `transform:
rotateX/rotateY` can tilt a flat plane in 3D *space* but can't give an
object actual volume — no real shading gradient across a curved surface,
no occlusion between faces. Genuine 3D needs a renderer. Added React
Three Fiber (WebGL) rather than faking it, and checked React 19
compatibility before installing (`@react-three/fiber@9.7.0`'s peer range
is `react >=19 <19.3`; this project is on `19.2.8`, inside the window) —
one version off in either direction and this would have been a much
worse afternoon.

Deliberately abstract primitive shapes (icosahedron, torus, box, cone,
capsule, octahedron), not literal controller/dice/joystick models: no
external `.glb` asset means no asset pipeline, no license question, and
keeps the same "hand-authored, self-contained" discipline the 2D genre
icons already established. Colors are read from the CSS custom properties
at mount (`getComputedStyle(...).getPropertyValue('--genre-1')`) rather
than a parallel hardcoded hex list — one source of truth for the genre
palette, same reasoning as everywhere else this palette is used. Lighting
is three manually placed lights (no `drei` `<Environment>` HDRI preset,
which pulls a texture from a CDN at runtime) — same no-external-asset
discipline extended to lighting, and it still reads as glossy/premium via
`MeshPhysicalMaterial`'s clearcoat property doing real work.

### Four lint findings that were real, not noise

The newer "React Compiler era" rules in `eslint-plugin-react-hooks`
(`react-hooks/purity`, `react-hooks/immutability`, `react-hooks/set-state-
in-effect`) flagged four things in the first draft of `HeroScene.tsx`.
Worth recording that none of these were dismissed as false positives
without checking first, even though three of the four are well-known
friction points between these rules and imperative libraries like React
Three Fiber:

1. `Math.random()` inside a render-path `useMemo` — a genuine purity
   violation, not a library-friction false positive. Fixed by deriving
   the per-object animation phase deterministically from the object's
   array index instead — same visual effect (objects bob out of sync with
   each other), zero randomness needed for what was only ever decorative
   variety.
2. Mutating `camera.position` (destructured from `useThree()`) inside
   `useFrame` — this **is** the standard, correct R3F pattern (`useFrame`
   exists specifically to mutate Three.js objects per-frame outside
   React's render cycle); the lint rule doesn't have a way to know that.
   Fixed by reading `state.camera` from the `useFrame` callback's own
   parameter instead of a hook binding destructured at the component's
   top level — same object graph, different AST shape, which is enough
   for the rule's pattern match to no longer trigger. This is the
   documented community workaround for this exact rule-vs-R3F conflict,
   not a project-specific hack.
3. One-shot `useEffect` + `setState` to read `prefers-reduced-motion` —
   fixed properly rather than silenced: replaced with
   `useSyncExternalStore`, React's actual mechanism for subscribing to a
   synchronous external value that can change after mount. Strictly
   better than what it replaced, not just quieter: the old version read
   the media query once on mount and never again, so toggling the OS
   setting mid-session while the tab was open wouldn't have updated
   anything; the new version does.

### A real, unrelated regression found along the way

Mid-slice, `uvicorn` (and `pip` itself) had gone missing from `.venv` —
broken in a way this session didn't cause directly (no `uv` commands were
run against this project between the last successful backend start and
this one). Recovered with the same `uv sync --extra agent` rebuild
procedure already validated once earlier in this project, rather than
investigating deeply — noted here as unresolved, not silently worked
around.

### Open questions (new)

- **Root cause of the venv regression is unknown.** Recovered, not
  diagnosed. If it recurs, worth checking whether something external to
  this session (a scheduled task, another tool, manual `uv` use in a
  different terminal) is touching `.venv` — the first two occurrences of
  venv corruption in this project both had a findable external cause
  (Windows file locks from a concurrent process); this one didn't get the
  same investigation.
- **The hero 3D scene is one fixed ensemble, not tied to which 8 genres
  are actually live.** It's deliberately decorative (a "the catalog has
  variety" statement, not a literal per-genre map) — the genre picker
  below does the real per-genre representation. Worth reconsidering only
  if that distinction stops being clear to a real viewer.
- **3D scene performance on lower-end mobile GPUs wasn't specifically
  profiled** — verified functionally correct (renders, no console errors,
  respects reduced-motion) on iPhone 14 emulation, but frame-rate under
  load on genuinely low-end hardware is unverified. Worth a real device
  check before treating this as deployment-ready.

---

## Slice 11 — A second Steam API, and the project's first real test suite

**Date:** 2026-08-27

Two questions arrived together: "is SteamSpy too limited, and should we
switch APIs?" and, separately, "how do we forecast real yearly trends?"
Worth untangling them, because they have different answers.

### Which API, and why not the ones proposed

SteamSpy's per-game endpoint gives owners/reviews/genre/price — enough for
most lookup and analysis questions, but nothing about release date,
Metacritic score, platform support, or feature tags (co-op, controller
support, Workshop). The user's own first proposal was three Steam Web API
endpoints from the official docs: `GetPlayerSummaries`,
`GetGlobalAchievementPercentagesForApp`, `GetNewsForApp`. Checked each
against what they actually return rather than taking the names at face
value: `GetPlayerSummaries` returns Steam *user* profile data (persona
name, avatar, online status) — it has nothing to do with games at all,
it's keyed on a Steam user id, not an appid. The other two are real but
narrow: achievement percentages is one metric, and news is unstructured
article text, neither is a general enrichment source. Said so directly
rather than building on top of a mismatch.

The actual fix was smaller than switching providers: Steam's own
storefront API, `store.steampowered.com/api/appdetails` — the same JSON
endpoint the Steam store website itself calls client-side to render a
game's page (confirmed by testing `?appids=620` for real and walking
through why the bare URL with no query param returns `null` — it's a
real API, just one that has no HTML front end of its own to visit
directly, unlike `store.steampowered.com/app/620` which is the actual
store page). Free, no key, no new account — same shape of win as the
existing SteamSpy/Steam-Web-API split, just a third source layered in the
same way. RAWG (20k free req/month) and IGDB (free via Twitch OAuth, rate
limited) were researched via WebSearch as real options for broadening the
*catalog itself* beyond what SteamSpy's bulk list returns, but that's a
bigger, separate scope decision (different client, different id space,
probably a merge/dedup step against the existing `appid`-keyed table) —
recommended treating it separately rather than folding it into this slice.

### What got built

`SteamStoreClient` (`src/ingestion/steam_store_client.py`) mirrors
`steam_web_client.py`'s existing pattern rather than inventing a new one:
same 1.5s rate-limit-between-calls approach, same on-disk JSON caching to
`data/raw/`, just a different cache-key prefix (`storeapi_` vs.
SteamSpy's own `appdetails_`) so the two caches can't collide. `run_ingestion`
now calls both APIs per game and merges the results in `_row_from_appdetails`.

Five new columns landed on `games`: `release_date` (parsed), `release_date_raw`
(kept as-is even when parsing fails — never silently drop the source
string), `metacritic_score`, `platforms`, `categories`. `categories` runs
through a hand-curated 15-entry allowlist (`CATEGORY_ALLOWLIST` in
`ingest.py`) rather than storing Steam's full ~30-tag raw list — most of
that raw list is controller/accessibility/remote-play noise that would
just add retrieval confusion for an agent trying to answer "does this
game have co-op" type questions.

Two real data quirks found by testing against a live response (Portal 2,
appid 620) instead of inventing fixture shapes:

- Its `categories` array has two different `id`s (51 and 30) that both
  carry the description "Steam Workshop" — a real duplicate in Steam's own
  data, not a parsing bug. Dedup logic keys on description, not id,
  specifically because of this.
- `platforms.mac` is `false` in the live response even though
  `mac_requirements` has actual text in it — meaning the authoritative
  signal is the `platforms.*` booleans, and inferring platform support
  from non-empty `*_requirements` text would have been wrong.

Both went straight into `tests/test_ingest_parsing.py` as
`REAL_PORTAL_2_CATEGORIES` — captured real data, not invented shapes,
specifically so the dedup logic is tested against the actual quirk that
motivated it.

The old `games.duckdb` was deleted and rebuilt from scratch rather than
migrated — the whole table is UPSERT-regenerable from raw ingestion and
gitignored, so there was no state worth preserving across the schema
change. This paid off for real mid-run: the full 1000-game re-ingestion
hit a genuine transient DNS resolution failure against
`store.steampowered.com` around appid 606280 (`getaddrinfo failed`, not
an API error — confirmed by re-resolving the same host seconds later and
getting a normal response) and the script has no retry logic around
network calls, so it crashed with a real traceback and a non-zero exit
code roughly 675-680 games in. Deliberately did not add retry/backoff
logic in response — the existing cache-first design in both API clients
already made this cheap: every successfully-fetched game (SteamSpy and
storefront alike) is cached to `data/raw/` before the crash point, so
simply re-running the same `ingest --count 1000` command picked up
exactly where it left off, re-fetching only the one failed game and
whatever hadn't been reached yet, instead of losing an hour of API calls
to one bad DNS lookup. Worth calling out as the resumable-cache design
actually earning its keep on a real failure, not just a theoretical
benefit.

Also added 5 new RAG schema chunks
(`src/agent/rag/schema_corpus.py`) so the agent can actually retrieve and
use these columns — worth calling out one wording choice: the
`metacritic_score` chunk explicitly says NULL means "not scored," not
"scored zero," because an LLM asked to rank by Metacritic score could
otherwise silently treat unscored games as the worst-rated instead of
excluding them.

### The project's first real test suite

No `tests/` directory existed anywhere in this project before this slice
— stats/forecast/viz logic had gotten real ad hoc verification during
their original slices (see Slice 4's entry for a real type-coercion bug
and a real group-mislabeling bug caught that way) but never a checked-in
regression suite. Built one from scratch: `tests/conftest.py` plus 6 test
files, 66 tests total.

The one deliberate philosophy, stated directly in `conftest.py`'s
docstring: prefer a real, throwaway on-disk DuckDB file over mocking this
project's own DB layer. The `games_db` fixture creates a genuine temp
DuckDB file, runs the real `CREATE TABLE` SQL from `schema.py`, and
inserts synthetic-but-realistic rows — so a test failure here means the
real schema/query code actually broke, not that a mock's assumptions
drifted from reality. `test_sql_guard.py` in particular runs one real
`DROP TABLE games` against a live fixture DB and asserts it's rejected
*and* the table is still there afterward with its 4 rows intact — testing
the actual guard behavior end to end, not just that a regex matched.

`pyproject.toml` gained a `dev` extra (`pytest`) rather than a
`[dependency-groups]` entry. That's a deliberate choice given this
project's history: `[dependency-groups]` installs by default on a bare
`uv sync`, and this project has already been bitten twice for real by
bare `uv sync` silently reconciling down to the lean base set (see
Slice 9b/README's warning) — adding `dev` as another *optional* extra
keeps that failure mode from getting worse, at the cost of needing
`--extra dev` explicitly to run tests locally.

A genuine test-authoring bug, found and fixed correctly: the first draft
of `test_outliers_finds_the_obvious_one` used 4 points (3 normal + 1
outlier) and asserted 1 outlier would be found. It found 0. Verified by
hand rather than assumed: mean ≈108, stddev≈219 with only 4 points, so
the outlier's own z-score (≈1.79) came in under the 2.5 threshold — a
real small-sample "masking" effect, where one extreme point inflates the
mean/stddev enough to pull its own z-score back down, not a bug in
`_outliers`. Fixed the test (20 clustered points + 1 outlier), not the
code, and left a comment on the test explaining the real effect so a
future reader doesn't "fix" it back to something smaller.

`.github/workflows/test.yml` runs the suite on every push/PR. First draft
used `uv sync --extra dev` only, with a comment claiming the LLM/RAG stack
wasn't needed for these tests — wrong, caught by actually tracing the
import chain: `test_stats_tool.py`/`test_forecast_tool.py` import
`stats_tool.py`/`forecast_tool.py`, which import `numpy`/`scipy`, which
live in the `agent` extra, not base. Fixed to `--extra agent --extra dev`
before considering the workflow done, rather than trusting the first
draft's comment.

A second real bug, found by actually re-running the suite exactly the way
the README/CI tell people to (`uv run pytest -v`) rather than trusting
that it still worked because it had passed once already:
`ModuleNotFoundError: No module named 'src'`, failing at `conftest.py`'s
own import. Root cause is a genuine, well-known pytest gotcha, confirmed
by testing both invocations directly: `python -m pytest` puts the current
directory on `sys.path[0]` (that's what `-m` does for any module), so
`import src` resolves; the plain `pytest` console-script entry point never
does that, so it doesn't. This project's tests had happened to be run via
`-m` (or an equivalent) during initial development, masking the gap until
a plain `uv run pytest` was tried. Fixed at the pytest-config level rather
than by telling people to remember `-m`: added `pythonpath = ["."]` to
`[tool.pytest.ini_options]`, pytest's own built-in mechanism for this
(since 7.0) — makes `pytest`, `uv run pytest`, and `python -m pytest` all
behave identically, and would have silently broken the CI workflow too
(same `uv run pytest -v` line) had it not been caught here first.

### Open questions (new)

- **`poll_player_counts.yml`'s catalog-rebuild step now costs meaningfully
  more CI time per 6-hourly run** — it re-ingests the full catalog just to
  get appids for the player-count poll, and now that ingestion also makes
  a storefront-API call per game with no cache persisted between GH
  Actions runs (`data/raw/` is gitignored). Noticed while re-reading the
  workflow for style conventions, not yet raised as a problem worth
  solving — a narrower "just fetch appids" path is the likely fix if the
  added runtime becomes a real issue.
- **Real yearly-forecast extrapolation still isn't built.** The user's
  actual ask ("delta players per year, then extrapolate") needs historical
  yearly snapshots that don't exist from any free source today. The
  `player_counts` table is the wrong series for this (6-hourly live CCU,
  not yearly). Proposed, not yet confirmed or built: converting the
  weekly `refresh_catalog.yml` re-ingestion into an append-only
  `owners_history` table, mirroring `player_counts`'s
  accumulate-don't-overwrite contract, so real year-over-year deltas
  accumulate naturally over time instead of being faked from one
  snapshot.

---

## Slice 12 — Naming Ludo, a "Meet Ludo" section, and a real catalog page

**Date:** 2026-08-27

Three asks arrived together: name the agent, add an intro section
explaining what it can do (floating gaming-object 3D iconography +
example questions), and build a separate full-catalog browse page. Named
the agent **Ludo** — offered a short list of directions (Ludo, Steamsight,
Datapad) and the user picked Ludo directly. Saved as a standing project
memory (`agent-name-ludo.md`) so future sessions use the name by default
in new copy without re-asking.

### A second 3D scene, and a real lesson about color and darkness

`GamingObjectsScene.tsx` needed five actually-recognizable objects
(controller, console, TV, disc, cartridge), not HeroScene's abstract
genre-colored primitives — a harder ask, since a controller only reads as
a controller if its grips/joysticks/buttons are legible, not just "a
lit shape." Built each as a small group of primitive geometries (drei's
`RoundedBox` plus core cylinder/capsule/sphere/torus primitives) — no
external `.glb` assets, same discipline as HeroScene.

First real render was nearly invisible: used `--surface-raised` (the
app's near-black 2D panel token, `#17181b`) as the chassis color, which
against the canvas's equally near-black background produced silhouettes
you had to squint to see (verified by actually rendering and screenshotting
it, not assumed fine because the geometry was correct). HeroScene's
objects don't have this problem because they're saturated genre hues, not
because of anything special about its lighting. Fixed with a dedicated
mid-graphite hex (`#6b6f79`) picked specifically for this scene rather
than reused from a 2D token — a color that works as a flat panel
background and a color that works as a lit 3D object's surface are not
the same design decision, even when the palette intent ("restrained,
neutral") is identical. Also had to fix the disc separately: its
`metalness=0.85, roughness=0.15` (very mirror-like) reflected essentially
nothing under this scene's 3-light setup (no environment map), so the
disc's body was invisible while only its accent ring showed — dropped to
`metalness=0.45, roughness=0.35` so it actually picks up diffuse light.
Deliberately did NOT reuse the genre categorical palette to color these
objects, even though it was sitting right there and would have been an
easy source of "more color" — that palette means something specific
elsewhere in the UI (which hue is which genre) and reusing it as pure
decoration here would manufacture a false mapping (a controller isn't
"Action-colored" for a real reason).

Pulled `useReducedMotion` out of `HeroScene.tsx` into
`lib/useReducedMotion.ts` the moment a second scene needed the identical
hook — no reason to fork it, and it's now the one place that logic lives.

### The catalog page's real sorting bug, caught before shipping

`src/db/catalog.py` filters and sorts in Python rather than building
dynamic SQL (the sort column is user input, and a column name can't be a
bound parameter — an allowlist dict is simpler and safer than templating
SQL). First implementation floored NULL values to a low sentinel (`-1`,
`date.min`) so they'd sort to the end — except that only works for
descending order; on ascending order a floored NULL sorts *first*, the
opposite of "always last" the code's own comment claimed. Caught this for
real via `tests/test_catalog.py::test_sort_by_release_date_ascending_puts_nulls_last`
failing, not by re-reading the code and spotting it — extended the
`games_db` fixture with real release dates on two rows specifically so
this test would be meaningful (all-NULL fixture rows can't test NULL
ordering against real values). Fixed by splitting rows into "has a value"
and "doesn't," sorting only the first group with the requested direction,
and appending the second group after — unaffected by `reverse`, so
NULLs land last regardless of ascending or descending.

### Real Playwright verification, not just unit tests

Ran the actual app (backend `uvicorn`, frontend `next dev`) and drove it
with Playwright (chromium, found already installed at
`~/AppData/Local/ms-playwright/chromium-1234` from earlier project work —
Python's `playwright` package needed the executable path passed
explicitly since its expected bundled Chromium revision didn't match
what was actually on disk) across both routes, both a desktop and a
mobile viewport: zero console errors, zero horizontal overflow, and
real interaction checks (typed a search term and read back the actual
filtered rows, selected a genre and verified every visible row's genre
field, clicked through to page 2 and confirmed the page indicator
updated) against the live 1000-game backend — not mocked, not assumed
from reading the component code. Also caught the catalog table's real
horizontal-scroll problem this way: 9 columns didn't fit in
`max-w-5xl` on an ordinary 1440px viewport, forcing a scroll a first-time
visitor wouldn't necessarily notice. Widened the catalog page specifically
to `max-w-7xl` (the ask-flow's own container stays `max-w-2xl` — a
focused single-question flow and a dense data table warrant different
widths, same reasoning that already put the hero at `max-w-5xl`).

Finished with the project's full pre-existing verification bar: `npm run
lint` (caught one real error — a plain `<a href="/">` where
`next/link`'s `<Link>` was required), `tsc --noEmit`, and `npm run build`
all clean, both routes prerendering as static content.

### Open questions (new)

- **The catalog table still needs its own horizontal scroll on narrow
  mobile viewports** (confirmed: no *page-level* overflow, but the table
  itself scrolls within its `overflow-x-auto` container past a few
  columns) — consistent with `ResultTable`'s existing behavior elsewhere
  in the app, but with no visual affordance (a fade/scroll hint) that more
  columns exist off-screen. Not fixed here; worth a real mobile design
  pass if this becomes a common complaint.
- **No URL-synced filter state on the catalog page** — search/genre/sort/
  page all live in component state only, so a copied catalog link always
  reopens to the unfiltered first page rather than reproducing what the
  sender was looking at. A reasonable follow-up if shareable catalog
  views turn out to matter, not built this round to keep the slice scoped.

---

## Slice 12b — A named real reference, and a lesson about drift

**Date:** 2026-08-27

Different kind of design request than the earlier "apply Kowalski/taste
directly" one: this time the user linked an actual live site
(framer.com) and named two colors (turquoise, black) rather than
describing a feeling. Scoped it with two quick questions before touching
anything, since both readings of "ditch the objects" were plausible and
expensive to get wrong: keep HeroScene's abstract shapes (they're already
working, already genre-colored, and weren't the thing being complained
about) and replace only the newer gaming-object scene; make turquoise the
one site-wide `--accent` rather than confining it to the new background.
Both confirmed directly rather than assumed.

### What "Framer-inspired" concretely meant here

Fetching framer.com's actual page didn't yield much — a markdown
extraction of a heavily-scripted marketing site loses essentially all of
the actual visual design (colors, blur, layout) and returns text content
instead ("earthy color palettes," organic-shapes copy — the *words* the
page uses to describe itself, not what it looks like). Worth naming
plainly rather than pretending the fetch gave real grounding: the actual
execution here came from well-established, genuinely common knowledge of
what that whole category of AI-product marketing page looks like (large
soft blurred gradient orbs drifting behind copy, not literal 3D
illustration) — combined with the user's own explicit color instruction,
which matters more here anyway since it overrides whatever hue Framer's
site actually uses today.

### The scene that got deleted, and what replaced it

`GamingObjectsScene.tsx` — five hand-modeled objects, real Playwright
verification, tuned lighting and materials — all deleted outright in one
turn, on direct instruction. Not kept behind a flag or commented out;
the user said ditch it, and half-removed code non-functional code is
worse than none. Replaced with `GradientBlobs.tsx`: three blurred
turquoise circles with slow independent drift, respecting
`prefers-reduced-motion` through the same shared hook the deleted scene
also used, plus a small inline SVG `feTurbulence` noise overlay — the
detail that keeps a large blurred gradient from banding, a real technique
this category of site actually uses, not decoration for its own sake.
Placed the gradient behind the *entire* "Meet Ludo" section (heading,
copy, chips) rather than in a small boxed illustration slot the way the
3D scene had been — a truer read of how this treatment is actually used
on sites like Framer's (an ambient field behind content, not a separate
diagram next to it).

### A real piece of accent-color drift, found by grepping before changing anything

Before touching `globals.css`, grepped the whole frontend for the old
hex (`f0a63a`) and the word "gold" rather than assuming the CSS variable
was the only place the color lived. Found one real case of drift:
`HeroScene.tsx`'s accent-colored point light was hardcoded to the literal
old hex instead of reading `--accent` like the object materials in the
same file already did — an inconsistency that would have silently kept
glowing gold after this slice's turquoise switch if the grep hadn't
caught it. Fixed to read the CSS variable live via `getComputedStyle`,
matching the pattern already used elsewhere in the same file, so a future
accent change won't need to remember this spot exists.

### Cleanup discipline, after last time

Left a background `uvicorn`/`next dev` pair running after the previous
slice's Playwright verification, which the user then hit for real as a
port-bind error in their own terminal. This time: identified and killed
both by the actual listening PID on ports 3000/8000 (`netstat` + explicit
`taskkill`) before considering the slice finished, not just before moving
on to the next task.

### Open questions (new)

- **No dark/light theme distinction was reconsidered for the turquoise
  swap** — this app is deliberately single-theme dark (see globals.css's
  own comment), so this doesn't apply yet, but worth remembering if a
  light variant is ever added: turquoise's contrast behavior on a light
  ground hasn't been checked at all.

---

## Slice 13 — A design brief for a different product, and what to keep from it

**Date:** 2026-08-27

Direct, blunt feedback arrived alongside a full ChatGPT-generated design
brief: "the website is not nice at all, I want it to be like this." Worth
being honest about what the brief actually specified before writing any
code, because it wasn't a redesign of Ludo — it was a complete spec for a
different fictional product: "PlayerLens AI," an internal analytics tool
for game *studios*, with example content built entirely around churn
rates, D7 retention, ARPDAU, and monetization cohorts (`mock-data.ts`,
`POST /api/agent` as a not-yet-real placeholder). None of that data
domain exists in Ludo's real catalog (SteamSpy + Steam storefront —
owners, reviews, price, genre, Metacritic, platforms), and Ludo's entire
premise — the thing that makes it a real project rather than a demo — is
that every number comes from a real query, never a mock.

### Separating craft from content before building anything

The temptation with a 250-line brief like this is to implement it
literally, since it's detailed enough to look like a spec. Resisted that
and asked two direct questions instead: keep Ludo's name/backend/real
data, or actually rebuild the product as PlayerLens with mocked churn
data? And separately, re-skin fully to the light Roman-marble look, or
just raise the craft bar on the existing dark identity? Both answers came
back the same direction: adopt the *visual language* (warm ivory, serif
headlines, restrained classical motifs, one royal-blue accent) while
keeping Ludo real. That's the actual scope this slice executed — a full
re-skin, zero fictional content anywhere on the page.

### What "restrained Roman" meant in practice, not in the brief's literal asks

The brief asked for a Colosseum background photo, a marble statue bust,
and a Corinthian column image (with fallback CSS if unavailable). None of
those got built — not because they'd look bad, but because sourcing
photographic imagery breaks a rule this project has held since Slice 9g
(HeroScene's abstract shapes over literal dice/controllers) and Slice
11/12b (every visual element hand-authored in code, nothing fetched):
no external image or model assets, ever. The brief's own instructions
actually argue for this independently — "architectural texture, not a
hero photograph," "must not look like Rome tourism," restraint over
literalism throughout. Built two hand-drawn SVG motifs instead: a laurel
sprig (`Laurel.tsx`, mirrored in pairs) and a single faint line-drawn
arch (`RomanArch.tsx`, opacity ~0.4 of an already-pale border color) —
plus an abstract ring-and-ticks medallion replacing the plain-text nav
logo. Three small elements, used exactly once or twice each, is
deliberately closer to the brief's own stated ratio ("80% modern SaaS,
15% classical, 5% game-specific") than anything more elaborate would
have been.

### The hero visual had to go, and what replaced it

Slice 12b's abstract 3D shapes (kept through the turquoise pass on the
strength of "already working, don't touch it") stopped being right the
moment the background went from near-black to warm ivory: saturated
genre-colored primitives read as toy blocks next to a serif headline on
a marble-adjacent palette, not as a premium product visual. Rather than
force them to survive a third re-skin, built `HeroPreview.tsx` — a
static floating panel showing a **real** answer Ludo already gave earlier
in this same session (the five highest-rated-games result, verified live
against the actual backend, not invented for this panel), styled as the
same card the real result view uses. This is actually closer to what the
brief's own hero concept wanted anyway ("a large floating application
panel... ChatGPT + Linear + modern BI dashboard"), and it keeps the
"everything on this page is real" rule intact where a mockup-style hero
illustration wouldn't have.

### A capabilities row grounded in the real graph, not the brief's four-item template

The brief's ASK / INVESTIGATE / EXPLAIN / ACT framework assumes a product
that gives recommendations ("ACT: turn insights into actions your team
can use"). Ludo doesn't do that — it answers questions, it doesn't
recommend business decisions. Rather than invent a fourth capability to
match the template's shape, used exactly the three things Ludo's real
pipeline (`router` → `retrieve_schema` → `agent` → `execute_tools`,
already documented in ARCHITECTURE.md) actually does: Ask, Investigate,
Show the work. Three real capabilities beat four templated ones.

### Fast reversal, named plainly

Slice 12b's turquoise accent shipped less than a day before this slice
replaced it with royal blue. Worth naming as what it is — a fast
reversal driven by direct user feedback that the previous pass wasn't
landing, not a mistake to smooth over in the log. The same "one
confident accent, changed cleanly through a single CSS variable, genre
palette untouched" mechanism held up for a third theme in a row, which is
exactly what having that mechanism was for.

### Verification

Same bar as every previous frontend slice: `npm run lint`, `tsc
--noEmit`, `npm run build` all clean; Playwright against both routes,
desktop and mobile, zero console errors, zero horizontal overflow, one
full real `/ask` round trip screenshotted to confirm the new accent and
panel styling actually reached the live result view, not just the hero.
Backend's 76 tests re-run as a sanity check even though this slice never
touched backend code. One operational note: the dev servers used for
verification this time were the user's own already-running instances
(recognized via a coincidentally-reused PID from the previous slice's
cleanup, still answering real requests) — pointed Playwright at the
existing ports rather than starting a competing pair, avoiding a repeat
of Slice 12b's leftover-server mishap by not spawning new servers at all.

### Open questions (new)

- **No `PlayerLens`-style mocked showcase was built anywhere** — the
  user's second answer confirmed "keep everything real" over "add a
  labeled mock section," so nothing on the page shows fabricated
  churn/monetization content. If a portfolio reviewer specifically wants
  to see how Ludo might extend toward studio-side analytics, that would
  need real design/scoping work (what data would that even require,
  where would it come from), not a mockup bolted onto this page.
- **The capabilities-row vertical dividers are quite subtle** on the
  light background (`divide-[var(--border)]`, the same pale warm-stone
  border used everywhere else) — intentional restraint, but worth a
  second look if a reviewer says the three columns don't read as
  separated at a glance.

---

## Slice 14 — Reverting fast, illustrating for real

**Date:** 2026-08-28

Direct rejection, no hedging: "I dont like this design at all." Paired
with four concrete new asks in the same message — a dark animated black/
green/turquoise background, a bolder "Apple style" font, a hand-
illustrated classical figure with gaming headphones holding a controller,
and Roman-styled genre icons. Unlike the PlayerLens brief two slices ago,
these were concrete and internally consistent enough to execute directly
rather than ask more clarifying questions — the user had already been
asked twice this session (Slice 12b's scope, Slice 13's re-skin-vs-craft
question), and a third round of questions on a message this specific
would have read as stalling rather than diligence.

### Reverting the mechanism, not just the values

Slice 13's light theme used a flat ivory background and a two-layer white
drop-shadow on every panel — neither survives a straight color swap back
to dark. A `box-shadow: 0 12px 28px rgba(...)` reads as "premium" against
flat ivory and reads as nothing (or a faint artifact) against a moving
dark gradient; dropped the shadow layer from `.panel` entirely and went
back to the flat hairline-bordered dark surface Slices 9g/12b already
proved out, rather than trying to make the light-theme mechanism work
with dark values plugged in.

### One fixed background layer, not a per-section effect

"Make the background animated" reads as a whole-site property, not one
section's decoration — the honest way to build that is one fixed,
full-viewport layer behind everything (`AuroraBackground.tsx`), not a
duplicated effect re-mounted in the hero and `MeetLudo` and anywhere else
separately. Made `body`'s own background transparent so the fixed layer
shows through in the gaps; content panels (the nav bar, `.panel` result
cards, the catalog table) keep their own opaque fills on top for
legibility, so a moving background never fights actually reading a data
table. `MeetLudo`'s own opaque section background (added in Slice 13)
came out for the same reason — it was blocking the aurora exactly where
the user would expect to see it keep going.

`lib/useReducedMotion.ts` — deleted three slices ago once nothing used
it — came back the moment AuroraBackground needed the identical hook.
Worth naming as real churn rather than smoothing it into the log: the
underlying need (something in this app wants to freeze under reduced
motion) is stable across redesigns even though which component needs it
keeps changing with every visual pass.

### The illustration, and a real layout mistake caught by looking

`RomanGamerBust.tsx` is the biggest new asset this slice: a hand-
authored SVG bust, not a fetched illustration or photo — the same
discipline every visual element in this app has followed since Slice 9g,
applied to something considerably more ambitious than a primitive shape
or a line-drawn arch. Chose a profile (cameo) pose deliberately over a
frontal face: a side silhouette is achievable with a handful of bezier
points and reads as intentional, where a frontal face attempted from
primitive shapes needs eyes/nose/mouth or it looks unfinished or eerie —
picking the pose that a modest set of hand-drawn curves can actually pull
off convincingly, rather than the pose that was asked for most literally.

First composition attempt overlapped the illustration behind the
`HeroPreview` real-answer card, offsetting the card only slightly. Real
mistake, caught by actually rendering and screenshotting it rather than
trusting the JSX: the card ended up covering almost the entire bust,
including the controller — the one detail the user had specifically
named. Fixed by stacking the two vertically instead of overlapping them,
which also sidesteps needing to tune two elements' relative z-order and
offsets to avoid occlusion on every future edit to either one.

### Genre icons: one consistent treatment, not ten bespoke redraws

"Make the icons more Roman style" could have meant redesigning all 10
hand-drawn glyphs in `GenreIcon.tsx` from scratch. Chose the cheaper,
more consistent option instead: wrapped each existing glyph in a circular
ring-bordered chip with an inset highlight (a coin/medallion frame)
rather than reinventing what each glyph depicts. This reads as a real
stylistic shift applied uniformly, and avoids the risk of some bespoke
Roman reinterpretation of "RPG" or "Simulation" losing the at-a-glance
legibility the current glyphs already have.

### A concrete "scroll" answer instead of another on-mount fade

Every animation in this app up to this slice was either an on-mount
stagger or a `whileInView` trigger — real, but not actually driven by
scroll position. Added genuine scroll-linked parallax (Motion's
`useScroll`/`useTransform` against the hero's own scroll progress) for
the arch line-art and the bust, drifting at different rates so they read
as sitting at different depths rather than moving as one flat layer —
the concrete version of "add transitions when you scroll down," not
another entrance animation.

### Verification

Same bar as every prior frontend slice: `npm run lint`, `tsc --noEmit`,
`npm run build` all clean; Playwright against both routes, desktop and
mobile, zero console errors, zero horizontal overflow, one full `/ask`
round trip screenshotted to confirm the new dark theme and turquoise
accent actually reach the live result view. Backend's 76 tests re-run as
a sanity check, unaffected by a frontend-only slice. Verified against the
user's own already-running dev servers again rather than starting a
competing pair.

### Open questions (new)

- **This is the fourth distinct visual identity this project has shipped**
  (Slice 9g's dark dev-tool look, Slice 12b's turquoise variant, Slice
  13's light Roman-marble pass, this dark-again illustrated one). Worth
  watching whether the next round of feedback converges on refining this
  one or triggers a fifth full pass — if it's the latter, worth explicitly
  asking what specifically isn't working before rebuilding again, since
  four full re-skins in one session is a real signal that something about
  how direction gets set (not the execution quality of any single pass)
  might be worth addressing directly.
- **`RomanGamerBust.tsx`'s facial profile detail (brow/nose/chin) is
  subtle at the rendered size** — visible on close inspection but reads
  mostly as a smooth silhouette at a glance. Superseded by Slice 14b's
  `RomanGamerStatue.tsx` (a front-facing figure, not a profile), so this
  specific concern no longer applies to the current illustration, but the
  underlying lesson (hand-typed bezier coordinates for a face read as
  "acceptable" more than "polished") carries forward to any future
  illustration work.

---

## Slice 14b — A real hydration bug, and building toward a real reference

**Date:** 2026-08-28

Two unrelated things arrived in one message: a genuine console error from
the user's own browser, and a reference photo with "let's use this
statue." Worth treating them as the different kinds of problems they
actually were — one a bug to fix correctly, the other a design direction
to interpret honestly.

### The hydration error: fixing the class of bug, not the instance

`Uncaught Error: Target ref is defined but not hydrated` from Motion's
`useScroll({ target: heroRef })`, added in Slice 14 for the hero's
scroll-linked parallax. Checked Motion's own troubleshooting page before
guessing at a fix: the documented cause is exactly "ref isn't properly
connected to a DOM element" at the moment `useScroll` needs it — and the
code here already looked like the documented-correct pattern (`heroRef`
attached directly to a plain `<div ref={heroRef}>`, no wrapper component
swallowing the ref). That's the tell that this is a timing race in how
Next.js App Router client components hydrate relative to when Motion's
internal effect fires, not a straightforward misuse the docs' checklist
would catch.

Rather than chase the exact race condition (client-only guard flags,
delaying the `useScroll` call until after a mount effect, etc.), switched
to the ref-free form of `useScroll()` entirely — it tracks raw
`window.scrollY` instead of a ref-relative scroll range, which structurally
cannot hit this class of error since there's no target ref to be hydrated
or not. Rewrote both parallax transforms against pixel scroll position
(`useTransform(scrollY, [0, 700], ...)`) instead of scroll progress
(0 to 1) relative to the hero's own bounding box — a small semantic
change (the parallax range is now a fixed pixel distance rather than
"across the hero's own height"), traded deliberately for removing an
entire category of hydration bug rather than patching one occurrence of
it. Verified with a fresh (non-HMR) Playwright page load plus repeated
programmatic scroll events, specifically because the original bug report
came from a live session that had been through many rapid HMR updates —
worth ruling out that as a contributing factor by testing a clean load.

### The statue: honoring the reference without embedding it

The shared photo was a real, specific classical marble statue — someone
else's photograph of a museum piece, copyrighted regardless of how it's
being used here. Two independent reasons not to embed it directly: this
project's standing rule (every visual asset in this app has been
hand-authored code since Slice 9g, no exception made yet for anything,
including a user-supplied reference image) and the more general point
that redistributing someone else's photograph inside a shipped product
isn't something to do on a user's behalf without them separately sourcing
usage rights for it. Said this plainly rather than silently either
embedding it or silently ignoring the request.

What did change for real: the illustration's whole composition. The
previous version (`RomanGamerBust.tsx`) was a shoulders-up profile bust —
reasonable, but nothing like what the reference actually showed (a full
standing figure, one arm raised holding a scepter aloft, a bold diagonal
gold drape, fuller curled hair). Rebuilt as `RomanGamerStatue.tsx` with
those same structural choices, translated to what the controller-holding
premise needs: the raised arm now holds the controller aloft instead of
a scepter, the gold drape is still gold and still diagonal (the
reference's one strong color note against white marble, kept rather than
forced into the site's turquoise to match chrome), and the hair is fuller
and curlier than the previous version's minimal treatment.

### A real geometry bug, caught by looking at the actual render

First draft of the raised arm used two independently-rotated rect
segments (upper arm + forearm) with two different, uncoordinated
rotation pivots. The math for each rotation was correct in isolation, but
the forearm's pivot didn't correspond to where the upper arm's rotation
had actually put its own endpoint — so the two segments didn't connect,
and the controller (positioned relative to the forearm's assumed end
point) rendered floating disconnected above the hand, not held in it.
Found by screenshotting the render, not by re-deriving the trigonometry
on paper — the same "verify against the actual output" discipline this
whole project applies to SQL results and stats computations applied here
to hand-drawn geometry instead. Fixed by simplifying to one rotated
segment for the whole raised arm, actually working out the rotation
trigonometry by hand for that single segment (pivot at the shoulder,
solved for the rotation angle that lands the far end at a target point
within the canvas), then placing the hand ellipse and the controller
group at that computed endpoint rather than an eyeballed one. One simple,
correctly-computed segment beat two more detailed but disconnected ones.

### Verification

`npm run lint`, `tsc --noEmit`, `npm run build` all clean. Playwright:
the fresh-load-plus-scroll check specifically targeting the reported
error (confirmed gone), plus the usual full pass (both routes, desktop +
mobile, zero console errors, zero horizontal overflow). Backend untouched,
76 tests still green.

### Open questions (new)

- **The bent (non-raised) arm in `RomanGamerStatue.tsx` reads as fairly
  subtle against the torso** — superseded by Slice 14c, which replaced
  the whole hand-drawn illustration with a real photo; no longer
  applicable, kept here only as a record of what the hand-drawn version's
  known rough edge was.
- **The parallax range change (pixel-based vs. hero-height-relative) means
  the exact drift distance is no longer proportional to the hero's actual
  rendered height** — fine at the viewport sizes this was checked at
  (1440×900 and 390×844), but an unusually tall or short hero rendering
  (e.g. a very wide ultrawide monitor, or a font-scaling accessibility
  setting that changes hero height substantially) could make the parallax
  feel slightly under- or over-scaled relative to how far you've actually
  scrolled past the hero. Not verified at other viewport sizes.

---

## Slice 14c — The first photographic asset, verified before use

**Date:** 2026-08-28

Two things arrived together, worth treating separately: a request to
connect Claude Code to Framer (a genuine research question, answered by
actually looking up what Framer's current external-agent feature does
rather than guessing from training-data-era knowledge), and then a
follow-up that reframed the real goal — "an agent that will help me
design an actual good website" — which named the real problem with this
whole session honestly: four full re-skins from me hand-writing CSS
blind is a worse loop than a tool with an actual visual canvas. Answered
that plainly rather than oversell what I can do without one.

Then, separately: "let's use Claude Design... add more realism with the
Roman statue... let's use a realistic statue of Apollo." Worth being
precise about what "Claude Design" actually is before acting on it —
looked it up rather than assumed: a real Anthropic research-preview
product at claude.ai/design, a separate browser surface I can't drive
from Claude Code, not a tool call available here. Said so directly. The
"realistic Apollo statue" part was the real, actionable request.

### Why a hand-drawn SVG can't do this, and what that implies

"Realistic" is a real requirement a hand-typed bezier path structurally
cannot satisfy — Slice 14b's `RomanGamerStatue.tsx` was already pushing
the ceiling of what primitive-shape illustration can achieve, and more
iteration on that ceiling wouldn't produce photorealism, just a more
polished non-photorealistic illustration. That's a different kind of
constraint than the ones this project has been solving with more careful
code (a sorting bug, a hydration race) — no amount of correct trigonometry
turns rectangles into marble. Said this directly rather than attempting
another SVG pass and hoping it read as more real than the last one.

### Scoping the real fork before touching anything

Three genuinely different ways to get a real photo exist, with different
costs: I find and verify a public-domain photo myself (breaks this
project's hand-authored-only rule, needs real license diligence on my
part); the user sources/generates one themselves and hands it to me
(sidesteps me making licensing judgment calls on their behalf); or stay
fully hand-drawn and accept the ceiling. Asked which, rather than picking
one — this is exactly the kind of fork where a wrong guess is expensive
(a licensing misstep isn't something to walk back quietly) and the
user's own risk tolerance is the actual deciding factor, not something I
can infer from the conversation so far.

### Verifying a license on the actual file, not the search summary

Found the Apollo Belvedere on Wikimedia Commons via search, but the
aggregated search summary just asserted "public domain photographs are
available" without naming which specific file or what license actually
applies to it — photographs of 3D public-domain objects are not
automatically public domain themselves (the photographer's framing,
lighting, and composition choices are their own copyrightable work,
unlike a straight photographic reproduction of a 2D public-domain
painting). Fetched the specific file's own Commons page directly and
confirmed CC BY 2.5, attributed to Marie-Lan Nguyen — a real, well-known
Wikimedia photographer of museum statuary — before downloading anything.
Attribution is a real license term, not a nicety, so it's rendered as a
visible caption under the image linking to the license text, not buried
in a code comment where only a reader of this repo would ever see it.

### Looking at the source before deciding how to use it

Downloaded the actual full photo and looked at it rather than assuming
"statue photo" meant "usable as-is." It's full nudity — normal and
expected for classical statuary, not appropriate for a product hero
image. Cropped to head/shoulders/extended-arm, which conveniently also
happens to be exactly the region needed anyway (the raised/extended hand
holding whatever will become the controller) — the crop decision served
two real constraints at once rather than being purely a workaround.

### Compositing with Pillow, and two more real bugs caught by looking

Built `frontend/scripts/compose-apollo-hero.py` (checked into the repo,
not left in scratch) to draw the headphones and controller directly onto
the photo with Pillow's `ImageDraw`, rather than trying to align live
HTML/CSS overlay elements against a photo's pixel coordinates across
every breakpoint — baking the composite into one static asset is far
more robust than keeping the alignment problem live in the browser.

Two real bugs, both caught by rendering and inspecting the actual output,
not by re-reading the script:

1. The controller rendered clipped off the right edge of the frame — the
   hand sits near the original photo's own right edge, and the rotated
   controller needed more canvas than that edge left available. Fixed by
   padding the canvas with transparent space before compositing anything
   onto it, rather than shrinking the controller to fit an edge that
   shouldn't have been the constraint in the first place.
2. After fixing that, a large solid black rectangle appeared where the
   transparent padding should have been. The fade-mask code computed a
   soft-edge gradient and then assigned it as the image's *entire* new
   alpha channel — silently discarding the padding's own alpha=0
   transparency and replacing it with the fade mask's default opaque
   value everywhere the fade gradient hadn't explicitly touched. Fixed by
   combining the fade mask with the pre-existing alpha channel via
   `ImageChops.darker` (a per-pixel minimum) instead of overwriting it —
   verified afterward with actual pixel-value checks (`getpixel` at
   several coordinates in the padding region), not just a visual glance,
   since the first "it looks transparent now" impression could easily
   have been the image viewer's own transparency rendering rather than
   confirmation the file was actually correct.

### Reproducibility over a one-off script

The compositing script downloads its own source photo on demand and
caches it gitignored rather than committing a ~5MB JPEG to the repo, and
lives in `frontend/scripts/` rather than a session-local scratch
directory — re-run from a clean checkout, it produces a byte-identical
`public/apollo-hero.webp`, verified for real by deleting the cached
download and re-running before calling this done.

### Verification

`npm run lint`, `tsc --noEmit`, `npm run build` all clean; Playwright
confirms zero console errors and zero horizontal overflow on both routes,
desktop and mobile, plus a real `/ask` round trip. Backend untouched, 76
tests still green.

### Open questions (new)

- **This is the first and only photographic asset in the app.** Superseded
  by Slice 15: the photo, and the whole identity around it, was deleted
  outright a few turns later on direct instruction to start over. Kept
  here as the real record of a decision that turned out to be temporary,
  not a mistake to erase from the log.
- **No `next.config.ts` image domain/remotePatterns change was needed**
  since the asset lives in `public/` rather than being loaded from a
  remote URL at runtime — moot now that the asset is gone, kept for the
  same reason as above.

---

## Slice 15 — The catalog is the identity, and a real bug in an LLM's own prose

**Date:** 2026-08-28

Two unrelated things landed back to back: the user installed a batch of
newly available Claude Code skills (superpowers, frontend-design, and
others), then immediately asked for a full landing page rebuild. Worth
treating that sequencing as real: this was the first task run through
`superpowers:using-superpowers` -> `superpowers:brainstorming` ->
`example-skills:frontend-design`, not because a skill happened to exist
for it, but because the rule those skills state plainly ("if a skill
might apply, invoke it, before any response") leaves no room to skip the
process just because six full re-skins already happened this session
without one.

### What the brainstorming gate actually bought

Classified the request as Bounded (an existing page's presentation, not a
new subsystem) and asked exactly one question before proposing anything:
does "completely new" mean rebuild the execution around the current
identity, or discard it and start over. The answer ("start over") is the
kind of fork that's expensive to guess wrong on after four prior re-skins
already spent that exact goodwill; asking once, concretely, cost nothing
and removed the single biggest risk in the whole task before any code
was written.

### The concept: stop illustrating the product, show it

Every prior direction (3D shapes, gradient blobs, a Roman statue) put a
decorative visual in front of Ludo rather than using anything Ludo
actually has. The frontend-design skill's own calibration section names
exactly the trap this session kept finding on its own the hard way:
AI-generated design defaults cluster around a few looks regardless of
subject. The fix here was to ground the hero in the one thing genuinely
specific to this product: its own real catalog. `CatalogField.tsx` plots
100 real games, live, fetched from the same endpoint the browse page
already uses, colored by real genre, sized by real popularity. Paired
with a real, named aesthetic risk: zero decorative accent color anywhere
in the chrome, so the only color on the entire site is real data. That's
the kind of choice the frontend-design skill calls "spend your boldness
in one place" made concrete rather than aspirational.

### A real Motion bug, caught immediately by the fresh Playwright pass

First render of `CatalogField` threw `<circle> attribute cy: Expected
length, "undefined"` on every single point. Root cause: `cy={p.y}` as a
plain JSX attribute alongside `cy: [...]` inside Motion's `animate`
object gave Motion nothing to interpolate from at the start of the
animation. Same family of bug as Slice 14b's controller-in-the-wrong-
place issue: something that looks structurally fine (a value defined
twice, once statically and once animated) actually leaves an undefined
gap Motion can't fill in. Fixed by letting Motion own `cy` completely,
defined in both `initial` and every branch of `animate`, never as a bare
prop.

Second, more interesting problem, found by looking at the actual render
rather than the code: a lot of real games share an exact price ($0,
$19.99), so the first working version showed hard vertical stripes of
stacked circles instead of a scatter. Fixed with a deterministic hash of
each game's own name for jitter, specifically not `Math.random()` during
render, a rule this project has held since Slice 9g's React-Compiler-era
fixes, and specifically stable across re-renders rather than reshuffling
positions every time.

### The dash constraint, and where it actually needed to be fixed

"No em dashes or en dashes" arrived as a hard constraint mid-slice. Fixed
every hardcoded string across the frontend, grep-verified rather than
spot-checked. But the real discovery came from actually running the
`/ask` flow after the rebuild: the live model's own answer came back with
a genuine em dash ("Aseprite – review score...") despite a new rule added
to the system prompt asking it not to use one. Worth stating plainly,
since it's a real, generalizable lesson: an instruction to an LLM changes
the distribution of what it outputs, it does not guarantee any specific
output. A constraint that has to hold for every response needs a
deterministic check on the output, not just a request in the prompt.

`_strip_dashes()` in `src/agent/graph.py` is that deterministic check,
applied on the one code path both `run_agent()` and `stream_agent()`
already funnel every route through, so the guarantee covers the API, the
MCP server, and evals without needing three copies of the same rule.
Found and fixed a real bug in this function before it shipped, the same
day it was written: the first regex (`\s*[—–]\s*`) matched a dash with
*zero* surrounding whitespace just as readily as one with real spaces
around it, so a tight numeric range like "10–20" was silently turned into
"10, 20", a list of two numbers instead of a range, changing what the
text actually meant. Caught by testing the fix against a real range
string, not just the original spaced-dash bug report, before considering
it done. Fixed by requiring real whitespace (`\s+`) before treating a
dash as a parenthetical aside; a bare dash falls through to a plain
hyphen instead, which preserves the range's meaning.

While verifying the live fix against the actual running backend, found a
third, related character in the same real response: U+2011, a
"non-breaking hyphen" that renders identically to a normal hyphen but is
a distinct Unicode codepoint, in "highest‑rated". Not literally an em or
en dash, and the user never named it, but it's the identical class of
problem: the model reaching for an unusual punctuation mark instead of
the plain ASCII one. Normalized it too, on the reasoning that the user's
actual intent ("plain, ordinary punctuation, not typographic LLM tics")
extends past the two examples they happened to name.

### Verification, run through superpowers' own gate

Invoked `superpowers:verification-before-completion` before making any
claim of done, which is stricter than this project's own established
habit of checking before wrapping up: every command (lint, `tsc`, build,
pytest, the dash grep, Playwright, a live curl against the running
backend) was re-run fresh in the same turn as the completion claim, not
reused from an earlier check in the conversation. All green: lint and
`tsc` clean, build exits successfully with both routes prerendering,
83 backend tests passing (6 new, covering `_strip_dashes()` directly,
including the range-preservation case and the non-breaking-hyphen case),
zero dash characters anywhere in rendered frontend strings, zero console
errors or horizontal overflow on both routes at both viewport sizes, and
a live model response confirmed to contain none of the three dash
characters.

### Open questions (new)

- **The hero's real-data scatter is sampled, not exhaustive.** It plots
  100 games (the top 100 by peak concurrent players, the same query the
  catalog page's default sort already uses), not all 1,000. That's a
  deliberate performance/legibility tradeoff, not an oversight, but it
  does mean the visual skews toward already-popular games rather than a
  uniform random sample of the whole catalog. Superseded by Slice 16:
  the scatter itself was replaced with a film strip of cover art a few
  turns later on direct "I dont like it" feedback, so this specific
  concern no longer applies, kept here as the real record.
- **Checked, not just assumed: `stream_agent()`'s progress events are
  node-completion markers (`stream_mode="updates"`), never token-level
  answer text.** The first draft of this entry claimed the sanitizer
  might momentarily miss a raw dash during live streaming; re-read the
  actual generator before leaving that claim in and it's not true, the
  frontend never sees the answer text until the one final, already-
  sanitized `AgentResult`. No real gap here, worth having verified rather
  than guessed.

---

## Slice 16 — Real feedback, real questions, a real palette lesson

**Date:** 2026-08-28

"I dont like it," aimed squarely at Slice 15's strict monochrome-plus-
live-data-scatter identity, arrived with four concrete replacement asks
bundled into one message: a Latin/Roman touch, a dark green background,
a sliding film-strip animation of real game covers, and different genre
icons and colors. Worth taking the rejection at face value rather than
defending the previous pass's reasoning: the scatter plot's honesty
(real data, no decoration) didn't matter if the result read as sparse
and cold rather than considered.

### Three questions, not four guesses

Ran this through `superpowers:brainstorming` again, the second time this
session the newly installed skill governed a design task, and asked
three targeted questions before touching any code: hotlink real Steam
cover art or fall back to placeholders, does the film strip replace the
scatter as the hero or run alongside it, and how far should "Roman
touch" go now that the full identity (aurora, statue, laurel icons) was
deleted outright one slice ago. All three of the biggest open forks in
this request got resolved with a nod each rather than an assumption,
which mattered more here than usual: getting "how much Roman" wrong in
either direction (too little reads as ignoring the feedback, too much
re-imports the exact system that was deliberately deleted last round)
would have wasted the whole turn.

### Real cover art, sourced the same way the Apollo photo was

Steam serves each game's own official cover art from a predictable CDN
path (`library_600x900.jpg`, the same asset the game's own store page
uses). Verified the URL was actually live with a plain curl before
writing any code that depended on it, the same discipline applied to
the Apollo photo's license two slices ago: check the actual thing
works, don't assume a URL pattern remembered from training data is still
current. This is the first *remote* image this app has ever loaded
(the Apollo photo was downloaded and committed; this one is hotlinked
live), which is a genuinely different reliability posture, if Steam
changes this path the strip degrades rather than breaks outright, since
each cover's `onError` handler drops it from the strip instead of
showing a broken image.

Getting the real cover art required a small, honest addition to the
data layer: `appid` wasn't previously exposed by `GET /catalog` because
nothing needed it yet. Added it to `_CATALOG_COLUMNS` rather than
building a separate endpoint, since the catalog page's existing rows
already carry everything else the film strip needs (name, for the
title attribute).

### The film strip's frame, built from real film mechanics

The sprocket-hole border isn't a repeated set of DOM elements, it's a
single `repeating radial-gradient` background tuned to the actual
spacing of real 35mm film perforations, which tiles automatically
regardless of the strip's rendered width. The double-rule bronze border
is the one Roman-adjacent touch on the frame; the genre icons' new
engraved-medallion ring (see below) is the other, deliberately two
small, specific accents rather than a reintroduction of the whole
system.

### A real, generalizable lesson from the categorical palette redo

The user asked directly for different genre colors, so this couldn't be
the existing validated default carried forward. Drafted an "earthy,
antique" 8-hue set first (rust, teal, gold, wine, olive, and similar)
to match the Roman mood the rest of this slice was reaching for, ran it
through the dataviz skill's actual validator against this app's own new
dark-green background rather than eyeballing it, and it failed
repeatedly. Reordering the same eight hues to separate the worst
adjacent pairs just moved the failure to a different pair. The real
lesson, worth generalizing past this one palette: eight hues clustered
in a narrow slice of the hue wheel structurally cannot clear adjacent-
pair separation floors no matter how they're ordered, because ordering
only changes *which* pairs are adjacent, not how close together the
hues are to begin with. Fixed by spreading the eight hues across the
full wheel (one blue, one orange, one teal, one gold, one magenta, one
green, one violet, one red) the same structural shape the dataviz
skill's own reference palette uses, just with different specific shades
so it reads as genuinely new rather than the same defaults restored.
That set passed every check on the first real attempt once the
structural constraint was respected instead of fought.

### Bringing the accent back, named as a reversal

Slice 15's "zero decorative accent color" was a real, deliberate risk
that didn't pay off. Reversing it isn't a quiet value swap: every
component that had been flattened to pure monochrome (the Ask button,
route/cached pills, the forecast's projected number, markdown bold and
links, the trace stepper) needed its accent usage restored individually,
since Slice 15 had rewritten each one to read foreground/muted directly
rather than through a variable that could be redefined once. Worth
naming that cost plainly: a "no accent" design choice isn't free to
reverse later if it was implemented by replacing every accent reference
rather than pointing them all at a token that happened to equal the
background at the time.

### Verification

Same fresh-in-this-turn bar as Slice 15's own close: `npm run lint`,
`tsc --noEmit`, `npm run build` all clean; backend's 83 tests untouched
and green; the dash grep re-run and still zero hits outside comments;
Playwright confirms zero console errors (including from the 80 remote
image requests the film strip's duplicated loop makes) and zero
horizontal overflow on both routes, desktop and mobile; a real `/ask`
round trip confirms the restored accent actually reaches the live
result view.

### Open questions (new)

- **The film strip's image requests (now 120: 60 real games, doubled for
  the seamless loop, up from 40/80 in the first draft) all fire on mount
  with no `priority` staggering.** No console errors or warnings
  surfaced from this in testing, but it hasn't been checked under a
  throttled/slow network condition, where a visible pop-in as covers
  load could look rougher than on a fast local connection.
- **Steam's CDN path for cover art isn't officially documented as a
  stable public API** — it's the same path the store page's own
  frontend uses, verified live before wiring this up, but Valve could
  change it without notice. No fallback exists beyond the per-cover
  `onError` drop; a Steam-side path change would just thin out the
  strip, not break the page, but worth knowing this dependency exists
  outside this project's own control.

---

## Slice 17 — A pausable marquee, done the boring reliable way

**Date:** 2026-08-29

Direct, unambiguous positive feedback on Slice 16 for the first time in a
while ("this a much bigger improvement thank you!"), followed immediately
by four concrete refinements rather than a rejection: widen the film
strip to full-bleed, a new font ("professional but also gamer like"), a
neon green hue, and a hover animation on the strip. Worth noting the
tone shift plainly: this is the first round this whole redesign arc
where the starting point was "keep this, make it better" rather than
"start over."

### Choosing Rajdhani for a specific, checkable reason

"Professional but also gamer like" is a real brief, not a vibe: it rules
out both a generic corporate sans (not gamer enough) and a novelty
pixel/display face (not professional enough, and this project has
rejected exactly that category of choice since Slice 9g). Rajdhani sits
in the specific middle this brief describes: squarish, technical
letterforms with real lineage in esports and gaming-HUD branding, but
regular/medium weights clean enough to still read as body copy rather
than a logo. Swapped in as the only sans face (still one face, no second
display font, the discipline Slice 15 settled on), not layered alongside
the existing one.

### The hover-pause, and why it's plain CSS instead of Motion

A sliding infinite loop needs to pause on hover so a viewer can actually
look at a cover, otherwise "hover animation" would just mean a bigger
visual jump when the mouse arrives. The film strip's slide was already
implemented with Motion's `animate` prop driving a repeating keyframe
tween. Stopping and restarting that same tween on hover risks a visible
jump: calling `.start()` again on a stopped keyframe animation
re-interpolates from the current value toward the *same keyframe list*,
which is not guaranteed to read as "frozen, then resumed," depending on
how Motion re-anchors the timeline. Rather than fight that, moved the
slide itself to a native CSS `@keyframes` animation
(`.filmstrip-track` in globals.css) specifically because
`animation-play-state: paused` is a browser primitive built exactly for
this: freeze in place, resume from the exact frozen position, no
interpolation math required. Verified this wasn't just a plausible
theory: read the track's own computed `transform` before, during, and
after a hover, and confirmed it changes while unhovered, stays bit-for-
bit identical for the whole hover duration, and `animationPlayState`
reads `paused` the entire time.

The per-cover scale-and-glow effect layered on top *is* Motion
(`whileHover` on each individual cover), and the two don't conflict:
the parent's CSS `transform: translateX` and each child's independently-
computed Motion `transform: scale(...)` apply at different points in the
CSS cascade/composition and don't fight for the same property on the
same element.

### Neon green, picked with the collision already in mind

The genre categorical palette already has a green (slot 6, a muted
olive-green, picked in Slice 16's validator pass). Making the site's one
UI accent *also* green risks the two reading as the same color doing two
different jobs, chrome versus data identity, coincidentally colliding.
Picked the neon accent (`#39ff88`) deliberately far more saturated and
bright than genre slot 6 rather than checking after the fact, so a
"glowing neon accent" and a "muted natural green data point" stay
visually distinct in the same view.

### Verification

Same bar as every prior slice: `npm run lint`, `tsc --noEmit`, `npm run
build` all clean; backend's 83 tests untouched and green; Playwright
confirms zero console errors and zero horizontal overflow on both
routes, desktop and mobile; a real `/ask` round trip stayed clean. The
hover-pause claim specifically got the programmatic check described
above, not just a screenshot that happened to show a scaled cover.

### Open questions (new)

- **Rajdhani's condensed, geometric letterforms haven't been checked
  against very long real answer text at small sizes** (the actual
  `/ask` result panel's body copy) — the hero headline and short UI
  labels read fine, but a long multi-sentence LLM answer at `text-sm` in
  a squarer face than Geist hasn't had a dedicated legibility pass beyond
  "it built and rendered without errors."
- **Neon green at full saturation on every accent use (buttons, links,
  the trace stepper, markdown bold) hasn't been checked for eye strain
  over extended reading** — fine for short labels and single words, not
  yet judged for a long markdown answer where multiple bolded terms in
  one paragraph would all carry the same bright accent.

## Slice 18 — A cartridge popup, and why the shared-layout morph got dropped before it was written

**Date:** 2026-08-29

Screenshot feedback on the catalog page's genre filter ("382 games")
turned out not to be a bug at all: the genre dropdown was set to
Adventure, and 382 is the real, correct count for that one genre inside
the 1,000-game catalog, not a data problem. Worth recording because it's
the first time this session a screenshot prompted an investigation that
resolved to "working as intended, here's why" rather than a fix.

The same message carried a real feature request: click a film-strip
cover to see that game's info in a popup styled like a video game
cartridge, close it back to the strip with an animation, and along the
way speed up the slide and drop the strip's side borders.

### Why the `layoutId` shared-element morph got dropped before any code was written

The initial pitch (presented to the user, not yet re-confirmed before
implementation started) described the cover art morphing from its
film-strip position into the cartridge via Motion's shared-layout
animation, `layoutId`. Before writing that, re-examined `FilmStrip.tsx`
and remembered its list is deliberately duplicated for the seamless
loop: `const strip = [...visible, ...visible]`. That means, at any
instant, two DOM nodes exist for the same `appid`, both mid-slide, both
candidates for the same `layoutId`. Motion's shared-layout animation
needs a single unambiguous source element to morph from; with two live
nodes sharing an id, which one it treats as "the" source is undefined
behavior, not a design choice this app makes on purpose. Rather than
give the strip's rendering scheme (duplicated list) more entanglement
with the modal's rendering scheme (single game), dropped `layoutId`
entirely and built a plain scale-and-fade `AnimatePresence` pop instead
(`GameCartridge.tsx`): it reads as "popping out" without depending on
which of two identical DOM nodes triggered it. This is the kind of
mid-task correction the brainstorming skill's design step exists to
catch, it happened here purely from re-reading the file being changed,
not from anything going wrong at runtime.

### One card, no second network call

Every field `GameCartridge` shows (cover, name, genre, release date,
Metacritic, platforms, price, review score, owners, peak players) is
already present on the `CatalogGame` object the film strip fetched to
build its cover list. Opening the cartridge is therefore a pure client-
side state change (`selected: CatalogGame | null`), not a new request to
the backend.

### Extracting `lib/formatGame.ts`

`CatalogClient.tsx` already had `formatDate`/`formatOwners`/
`formatPrice`/`formatPlatforms` as private local functions for its
table. The cartridge needed the exact same formatting for the exact
same fields. Rather than let a second copy exist and drift (a null
price rendering differently in the table than in the cartridge, say),
pulled all four into `lib/formatGame.ts` and pointed both consumers at
it. `CatalogClient.tsx`'s own `PlatformBadges` component was retired in
the same pass since `formatPlatforms` returns a plain string now, not
JSX; the table cell just calls it directly.

### Pausing the strip while the cartridge is open

The Slice 17 hover-pause (`animation-play-state: paused` on `:hover`)
only fires while the pointer is still over the strip, which usually
isn't true once someone has clicked a cover and is reading the
cartridge with their mouse elsewhere. Added a second, independent path
to the same CSS property: an inline `animationPlayState: selected ?
"paused" : undefined` alongside the existing `:hover` rule, so the
slide is guaranteed frozen for the entire time a cartridge is open
regardless of pointer position, and resumes the instant it closes.
Verified this the same way Slice 17 verified the hover case: read the
track's computed `animationPlayState` immediately before opening
(`running`), while open (`paused`), and immediately after closing
(`running` again) rather than trusting the CSS rule to behave as
intended.

### Speed and border, the two small direct requests

The slide's duration multiplier dropped from `visible.length * 2.2`
seconds to `* 1.2`. The strip's frame border, previously `3px double
var(--accent)` on all four sides, is now `borderTop`/`borderBottom`
only, with no left/right rule, matching the direct ask for "an upper
and bottom border, however on the side nothing."

### Verification

`npm run lint`, `tsc --noEmit`, `npm run build` all clean; backend's 83
tests untouched and green (this slice is frontend-only). Playwright,
run twice: once confirming the border computes to 3px top/bottom and
0px left/right, a click opens the dialog, the X button closes it, and
`animationPlayState` reads `paused` while open and `running` after
close, at both desktop and mobile viewports with zero console errors
and zero horizontal overflow on `/` and `/catalog`; a second pass
specifically isolating the two other close paths (Escape and a backdrop
click), since "click X on it" was the only close path spelled out
explicitly and the other two were part of the design, not just an
implementation detail. Grepped every new and touched file for em
dashes, en dashes, and non-breaking hyphens; none found outside code
comments.

## Slice 19 — Actually deployed, and two real gaps the deploy itself surfaced

**Date:** 2026-08-29

Everything up to this point had been verified against `localhost` only.
Asked directly "how do I deploy this, and do I still need to run
uvicorn/npm run dev myself" — the answer to the second half is no, once
deployed the platforms run the servers continuously on their own
infrastructure, the local dev commands become a pure local-dev loop.

### Correcting the repo's own advice before following it

The README's Deploying section (written back in Slice 6) recommends
"Render or Fly.io" interchangeably. Rather than trust that unchanged,
checked current terms first, since hosting free tiers are exactly the
kind of fact that goes stale: Fly.io removed its free tier for new
accounts back in 2024 (a 2 VM hour/7 day trial, then a card is
required), while Render's free web service tier still needs no card at
all. Used Render only. Same instinct as verifying the Steam CDN URL
with a live curl before hotlinking it in Slice 16, applied to a
pricing claim instead of a technical one.

### The Health Check Path trap

Render's own new-service form shows `/healthz` as greyed placeholder
text in the Health Check Path field — common convention on other
platforms, but not this app's actual route. The real endpoint is
`GET /health` (`src/api/main.py`). Typing the placeholder literally,
rather than reading it as an example, would have pointed Render's
health monitor at a 404 and likely marked the service unhealthy despite
it actually running fine.

### Build Filters, added because most commits in this repo are irrelevant to the backend

Left unset, every commit to `master` triggers a full Render rebuild,
including a full Docker build and the ~25-minute SteamSpy re-ingestion
step. Looking at this project's own commit history, the overwhelming
majority of commits are frontend-only or documentation-only (this
project's own habit of updating PLAN/DOCEXP/README after every slice).
Added Ignored Paths (`frontend/**`, `*.md`, `.github/**`) so those
commits redeploy the frontend on Vercel (fast, no ingestion involved)
without also triggering a wasted 30-minute backend rebuild that changes
nothing. Chose an ignore-list over an allow-list deliberately: a
forgotten future backend path still deploys correctly under an
ignore-list (fails safe, just an occasional unnecessary rebuild); under
an allow-list, a forgotten path means a real change silently never
ships (fails unsafe, and is a much worse thing to debug later).

### Two real gaps the deploy step itself surfaced, not hypothesized in advance

**Vercel offered to import 26 environment variables it detected across
the whole repo, not just `frontend/`.** These came from `.env.example`
(root, ~25 backend-only vars) plus `frontend/.env.local.example` (the
one real one). All 25 backend vars had empty values, since the actual
`.env` with real values is gitignored and was never visible to Vercel's
GitHub-based import, so nothing sensitive was ever at risk, but
importing them all would have left 25 dead, confusing entries sitting
in a frontend project that never reads any of them. Removed all but
`NEXT_PUBLIC_API_BASE_URL`.

**`CORS_ALLOWED_ORIGINS` was missing entirely from Render's environment,
not merely left at a default value on purpose.** The backend had been
set up via Render's "Add from .env" shortcut against the real local
`.env` file — and that file, unlike `.env.example`, had never actually
included a `CORS_ALLOWED_ORIGINS` line (or `DEBUG`, or the rate-limit/
cache tuning vars — those simply hadn't been needed for local dev,
where the code's built-in defaults already matched what local dev
wanted). Because `src/config.py`'s `Settings` class gives
`cors_allowed_origins` a default of `http://localhost:3000`, the
missing variable didn't cause an error or a crash, which is exactly
what made it easy to miss: the service came up green, `/health` was
fine, and the only visible symptom was the deployed frontend's fetches
failing with a CORS rejection once Vercel was live. Added the variable
explicitly rather than relying on the default resolving correctly by
coincidence.

Picked "Save and deploy" over "Save, rebuild, and deploy" for this
fix specifically: `CORS_ALLOWED_ORIGINS` is read at container startup,
not baked into the image at build time, so a full Docker rebuild (and
therefore a second ~25-minute re-ingestion) would have been pure waste
for a change that only needs a container restart with a new
environment variable.

### Verification, against the live URLs this time, not localhost

`curl https://ai-game-analyst-api.onrender.com/health` confirmed
`db_exists: true` in production, not just that the container booted.
An `OPTIONS` preflight against `/ask` with a real `Origin:
https://full-stack-project-sepia-nine.vercel.app` header confirmed the
response's `access-control-allow-origin` echoes that exact URL, not a
wildcard or a stale `localhost` value left over from before the fix.
Playwright driven against the live Vercel URL (not localhost)
confirmed real Steam cover art loads, a click opens the cartridge and
Escape closes it, `/catalog` renders real rows, and zero console errors
or horizontal overflow at both desktop and mobile viewports. A live
`POST /ask` against the deployed Render backend, not a local one,
returned a correct route classification (`analysis`), correct SQL, and
a correctly formatted markdown-table answer with no em/en dashes. This
is the first slice where "verified" means verified against the actual
public URLs a stranger would hit, not against a machine only I can
reach.

### Open questions (new)

- **No live-URL smoke test runs automatically.** Everything above was
  checked by hand, once, right after deploying. A future code change
  could break the live site (a bad env var, a CORS regression, a
  broken build) with nothing catching it until someone happens to
  visit and notice — there's no scheduled or post-deploy check hitting
  the real URLs the way `test.yml` hits the test suite on every push.
- **The Render free tier's 15-minute spin-down is real and unverified
  under a genuinely cold start.** Every check in this slice happened
  while the service was already warm from the deploy itself; the
  actual 30-60 second cold-start delay after real inactivity hasn't
  been observed directly yet.

## Slice 20 — The answer was correct and completely invisible

**Date:** 2026-08-29

Live-site usage surfaced the first real UX bug found by actually using
the deployed product rather than by reading code: asking a question
gave no visible feedback near the input, and the answer rendered
somewhere off-screen. Worth noting the sequence, since it started as a
misread: while investigating, a Render log full of `huggingface.co`
HEAD requests and an orange `HF_TOKEN` warning looked alarming at
first glance, but turned out to be completely normal (a cold-start
embedding-model cache verification, not a failure — no exception, no
non-2xx from the app itself, and the screenshot alongside it showed the
question had actually answered correctly). Worth recording as a small
lesson on its own: color-coded log severity (Render highlights WARNING
lines in orange) is not the same signal as "something is broken," and
reading the actual HTTP status codes and outcome mattered more than
the visual alarm color.

### The real bug, confirmed by reading the code, not just the report

`app/page.tsx`'s layout put the ask bar near the top, then rendered
`MeetLudo` and the genre showcase in full below it, and only after
both of those did the progress trace and result actually appear.
Clicking Ask changed the button label to "Asking…" and nothing else
visible happened until the user scrolled past two entire sections that
have nothing to do with the question they just asked.

### The fix, and why it needed more than moving one `<div>`

Relocating the trace/result block to sit directly under the ask bar's
example-question pills solves the problem for the main input, but this
app has two other entry points that call the exact same `ask()`
function from much further down the page: Meet Ludo's example
questions and the genre showcase's leaderboard picks. Moving the
result block up without anything else would have just relocated the
bug rather than fixed it for those two paths — triggering a question
from the bottom of the page would then show the answer scrolled far
above the click, same underlying problem, opposite direction. Added a
ref-anchored `scrollIntoView({ behavior: "smooth" })` inside `ask()`
itself, so every entry point converges on the same fix regardless of
where the click originated. Also added an explicit "Ludo is
thinking…" label above the trace dots — the dots alone (five grey
circles, one pulsing) read as decoration at a glance if you don't
already know what they mean; a plain-language label removes that
ambiguity for a first-time visitor.

### The chat feature: recommended against building it as scoped, not silently dropped

The same feedback asked for a bigger change: a ChatGPT-style
multi-turn thread, so a person could ask a follow-up like "compare
that to Elden Ring" and have the agent understand what "that" refers
to. Looked at this honestly rather than defaulting to "sure, more
features": the specific use case named, comparing two games, is
already served today by the existing stateless `run_stats`
`compare_two_groups` tool inside a single question (one of this app's
own example questions already exercises it). Building real
conversational memory to serve that same use case would mean teaching
the router and prompts to resolve cross-turn references, deciding
whether follow-up context should influence SQL generation and how that
interacts with the SQL-safety guardrails, and building genuinely new
frontend state — a real architectural undertaking, not a UI tweak.

Recommended against it specifically because of what it would trade
away, not just its size: this project's actual differentiator among
portfolio projects a technical reviewer will have seen many of isn't
"it's a chatbot" — it's the guardrails (guaranteed SELECT-only SQL, a
router that gates tool access, real statistics instead of an LLM
eyeballing an average, evals with live-computed ground truth). Adding
cross-turn context specifically increases the surface area that safety
story has to cover, for a feature whose stated use case the stateless
pipeline already handles. If full conversational memory is wanted
later specifically to demonstrate that skill for a job application,
that is a legitimate reason on its own — but it deserves its own
brainstorm and its own slice, not to be folded into a loading-state
fix.

### Verification

`tsc --noEmit`, `npm run lint`, `npm run build` all clean. Started a
real local backend (not mocked) and drove the actual UI with
Playwright: confirmed "Ludo is thinking" and the trace panel are both
inside the viewport immediately after clicking Ask, with zero
scrolling, at both desktop and mobile widths; a second run clicked an
example question rendered well down the page and confirmed the page
auto-scrolled and the trace panel became visible, proving the fix
covers all three entry points, not just the one that was reported.
Zero console errors in either run. Grepped the new copy for em dashes,
en dashes, and non-breaking hyphens — the only new punctuation is a
plain ellipsis ("Ludo is thinking…"), not a dash, and none were found.

### Open questions (new)

- **Full multi-turn conversational memory remains unbuilt, on
  purpose** — see the reasoning above. Worth revisiting only if there's
  a specific reason (a target role's job description calling out
  multi-turn agent memory, for instance) that outweighs the guardrail-
  surface-area cost, and it should get its own brainstorming pass
  rather than being added incrementally.

## Slice 21 — Portfolio/hygiene cleanup pass

**Date:** 2026-08-29

A deliberate stock-take rather than a feature: after Slice 19's deploy
and Slice 20's UX fix, took a step back and listed everything still
open before doing more feature work. Two real, self-inflicted findings
came out of just checking git state honestly:

**`render.yaml` wasn't covered by Render's Ignored Paths, and it
mattered immediately, not hypothetically.** The Slice 19 doc-fix commit
touched `render.yaml` (correcting its stale Fly.io comment and
placeholder CORS URL), and because that file wasn't on the ignore
list, it almost certainly triggered a real, wasted Render rebuild —
caught by checking `git show --stat` on the pushed commit, not by
guessing. Added it to the ignore list.

**Dead 3D dependencies were still costing install/bundle weight for
zero functional benefit.** `@react-three/fiber`, `@react-three/drei`,
`three`, and `@types/three` survived Slice 14's WebGL statue hero being
deleted, sitting unused in `package.json` since. Confirmed zero imports
across `app/`, `components/`, `lib/` before removing anything (same
discipline as every other deletion in this project's history — grep
first, never assume). `npm install` afterward dropped 54 packages;
`tsc --noEmit`/`lint`/`build` all still clean, and the build's own
compile step measurably faster (1.3s vs 2.7s) with less to bundle.

### Adding a LICENSE, and being explicit about the name on it

The repo had no LICENSE file at all — a real gap for a public portfolio
project, since without one the legal default is "all rights reserved,"
which is a strange stance for something meant to be read and judged by
strangers. Added MIT, the conventional default for exactly this kind of
project. Used the GitHub-facing identity (`stefhooy`, the name every
commit in this repo is already authored under) as the copyright holder
rather than inserting a real legal name unasked — easy to swap for a
different name if a real one is preferred.

### `frontend-ci.yml`: why it exists and what it actually catches

Every frontend verification in this project's entire history, across
every one of the last several slices, was a manual pass: run `tsc`,
run `lint`, run `build`, run Playwright, by hand, in the same
conversation turn as the change. That's real verification in the
moment, but it proves nothing about the *next* commit. Nothing before
this slice would have caught a future change that broke the frontend
build, introduced a type error, or failed lint, unless someone happened
to run those commands again by hand. `test.yml` already covers exactly
this need for the backend (pytest on every push/PR); `frontend-ci.yml`
is the same idea for the frontend, deliberately mirroring `test.yml`'s
structure and commenting style rather than inventing a different
pattern for the same job.

Scoped to `frontend/**` via `paths:`, for the identical reason Render's
Ignored Paths exist: a backend-only or docs-only commit has no way to
break the frontend build, so re-running it on every unrelated push
would just be wasted Actions minutes for zero additional signal.

Verified the workflow's three steps would actually pass, not just that
the YAML parses: killed lingering local Node processes holding a file
lock, ran a genuinely fresh `npm ci` (not a warm `npm install`, to
match what a CI runner actually does), then ran `lint`, `tsc --noEmit`,
and `build` in that exact order against that fresh install. All three
passed. `NEXT_PUBLIC_API_BASE_URL` is set to a harmless placeholder in
the workflow env — `lib/api.ts` already falls back to
`http://localhost:8000` when the variable is unset, so this is
belt-and-suspenders explicitness rather than a functional requirement;
the build never calls the real backend regardless; it only proves
Next.js's static generation and type checking succeed.

### ruff + mypy for the backend, and fixing what they actually found

Backend static analysis was the next item down Slice 21's list. Chose a
moderate ruff rule set (`E, F, I, UP, B, BLE, RUF`) rather than every
plugin ruff ships: `E/F` is the real correctness baseline, `I` sorts
imports, `UP` modernizes for the 3.12 target, `B` (bugbear) catches
real bug shapes, `RUF` is ruff's own checks. `BLE` (blind-except)
specifically because `src/api/main.py` already had a `# noqa: BLE001`
comment on a broad `except Exception:` before this config existed —
the codebase was already anticipating this exact rule, so enabling it
just made an intent that was already written down actually enforced.
Left `DTZ` (flake8-datetimez, "always pass tzinfo") out on purpose: this
codebase has one consistent convention instead of an oversight —
timestamps are written UTC-aware once, at the single point they're
created (`poll_player_counts.py`), and read back naive everywhere else
because that's genuinely what DuckDB's Python API returns for a
TIMESTAMP column. Enabling DTZ would have flagged the tool and its
tests as buggy for correctly matching their one real data source.

For mypy, deliberately not `--strict`: LangChain, LangGraph, and DuckDB
don't ship complete type stubs, and strict mode on day one would mean
either a wall of blanket `# type: ignore` at every library boundary or
hours spent stub-hunting instead of catching real mistakes. Picked a
level that catches real bugs (`check_untyped_defs`, `warn_unused_ignores`,
`warn_redundant_casts`) while tolerating untyped third-party surfaces
(`ignore_missing_imports`), with room to tighten later once those
boundaries get individually reviewed instead of ignored wholesale.

**What actually turned up, and why every finding got fixed rather than
suppressed:** 33 ruff issues and 13 mypy issues, all real, none of them
"turn off the rule and move on." The two categories worth remembering:

- **Ambiguous-unicode false positives in exactly the two files that are
  supposed to contain literal em/en dashes** (`graph.py`'s
  `_strip_dashes()` and its test) — the one case in this whole pass
  where the right fix genuinely was a per-file ignore, since the
  characters ruff flagged are the entire point of that code, not stray
  punctuation. Scoped the ignore to those two files specifically, not
  project-wide, so the rule still does its job everywhere else.
- **Four functions typed `list[list]` when their only real caller
  (`run_guarded_query`, DuckDB's own `.fetchall()`) actually returns
  `list[tuple]`.** This was a real, if harmless-in-practice, type
  mismatch that would have let a genuine bug (accidentally relying on
  list-only behavior, like item assignment) through undetected.
  Widened the parameter type to `Sequence[Sequence[Any]]` — the
  functions only ever read `rows`, never mutate it, so the more
  permissive, correct type was the actual fix, not a workaround.
- **Two `with_structured_output()` calls** (the router, the eval
  judge) **typed looser than they resolve at runtime.** LangChain's
  stub allows either a `dict` or a `BaseModel` back, since the method
  also accepts a raw JSON-schema dict as its target — but passing a
  Pydantic model class, as both call sites do, always returns an
  instance of that exact class. Used `cast()` with a comment explaining
  why, rather than restructuring working code around a stub's
  generality it doesn't actually need.
- **`ChatGroq`'s `api_key` expects a `SecretStr`, not a plain `str`.**
  A real, if minor, type gap — wrapped it. This one actually touches a
  live code path (every real Groq call), so it got the same live
  verification as the SSE change below, not just a type-checker pass.
- **A duplicated long f-string, not just a long line.** Ruff's line
  length flag on one `yield f"data: {json.dumps(...)}\n\n"` in
  `ask_stream()` led to noticing it was the third near-identical copy
  of the same SSE-framing pattern in that function. Extracted a small
  `_sse()` helper instead of just wrapping the line — a real
  deduplication the line-length check surfaced as a side effect, not
  the fix ruff was actually asking for.

### Verification

`ruff check src/ tests/` and `uv run mypy src/` both clean. Re-ran the
full 83-test pytest suite after every fix landed, not just at the end —
still 83 passed. Because two of the fixes (the `SecretStr` wrapper
around the real Groq API key, the extracted `_sse()` helper inside the
actual `/ask/stream` handler) touch genuine request paths rather than
being pure type-annotation changes, started a real local backend and
drove both `POST /ask` and `POST /ask/stream` with real questions
against the live Groq API afterward — both returned correct answers,
correct SQL, and (for the stream) the expected node-by-node progress
sequence, confirming the refactor didn't silently change runtime
behavior. Also simulated the exact CI workflow order locally (`uv sync
--extra agent --extra dev` fresh, then ruff, then mypy, then pytest, in
that sequence) rather than trusting the YAML would behave the same as
running the commands by hand.

### A small ARCHITECTURE.md accuracy fix, found while checking whether it needed one

Asked directly whether ARCHITECTURE.md needed updating for Slices
18-21's work. It didn't — that document is deliberately scoped to the
reasoning system's shape (the graph, RAG, the safety boundary), not
deployment topology or frontend UI or dev tooling, and none of those
slices touched that shape. But checking it against the real code
surfaced a genuine, pre-existing staleness unrelated to recent work:
the System overview diagram's FastAPI node listed `/ask, /ask/stream,
/genres, /games` without `/catalog`, which has existed for several
slices. Fixed the diagram, and also noticed `catalog.py` — which
bypasses `connection.py` the same way `genre_stats.py` does — wasn't
represented as a box at all. Combined them into one box and rewrote the
explanatory bullet to state their actual, slightly different safety
reasoning accurately rather than imply they're identical: `genre_stats.py`
has no user input at all; `catalog.py` has real user input (search,
sort, genre filter) but never lets it reach a SQL string, routing sort
through a Python allowlist dict and filtering in Python after one
unparameterized fetch instead.

## Slice 22 — A RAG retrieval eval, and confirming the eval itself wasn't fake

**Date:** 2026-08-29

Every eval this project has had so far checks the final answer: is the
number right, is the route right, is the LLM judge satisfied. None of
them check the one step in between — does `retrieve_schema` actually
pull in the right context for a given question. A final answer can
sometimes come out right even when retrieval grabbed the wrong or
incomplete chunks (the LLM might already "know" the schema well enough
from the question itself, or get lucky), so "the answer was correct"
is not the same claim as "retrieval did its job." This slice built a
way to check the second claim directly.

### The free-eval discovery that shaped the design

Before designing anything, read `schema_index.py` and
`schema_corpus.py` rather than assuming how retrieval works. That
surfaced something that changed the whole approach: `SchemaIndex.retrieve()`
only calls `get_embedder()` (the local ONNX model via fastembed) — it
never touches Groq or any paid API. Every other eval in this project
(`run_evals.py`'s golden questions) needs a real LLM call per question,
which is exactly why that harness stays manual-only, cost- and
rate-limit-gated. This one doesn't have that constraint at all. That
single fact moved the whole feature from "another manual report to run
occasionally" to "a real pytest test that gates CI for free, forever."

### Excluding `always_include` chunks from the golden set, on purpose

`schema_corpus.py` marks four chunks (`table:games`, `column:name`,
`column:genre`, `table:player_counts`) as `always_include=True` — they
bypass ranking entirely and come back regardless of the question,
because semantic similarity alone was empirically found (Slice 2/9) to
under-rank generic-sounding columns like "name" against a question
naming a specific game. Including these in the golden set's expected
answers would have made the eval measure nothing real: they'd show up
100% of the time by construction, inflating the score without the
ranking algorithm having done any work. The golden set only tests the
~30 chunks that actually have to compete on similarity to be retrieved.

### Measuring before locking in a bar, and proving the measurement means something

Rather than pick a target recall number, measured what the real system
actually achieves first: **recall@8 (production's real `RAG_TOP_K`)
came back 1.000** across all 15 hand-labeled questions. Before trusting
that as a real baseline rather than an artifact of a too-easy test,
checked whether the eval could actually tell good retrieval from bad by
re-running at a much smaller k: recall@3 dropped to 0.789, recall@1 to
0.522, with real, specific misses reported (e.g. `dev_publisher` scored
0 at k=3 — the developer/publisher columns didn't make the cut at that
tight a limit). That confirmed the eval has real discriminating power,
not just a design that trivially always passes regardless of k, so the
1.000 at the real k=8 is an earned, meaningful result and not a red
flag. Also confirmed the result is deterministic across repeated runs
(no randomness in embedding computation for fixed input text) before
locking `1.0` in as the exact regression bar — a bar grounded in what
was actually measured, not a guessed target picked in advance.

### A quick honesty check on the 15 questions themselves

Cross-checked every chunk ID referenced in the golden set against the
real corpus programmatically (a small script comparing the two id sets)
rather than trusting hand-typed IDs — caught zero typos, but this is
exactly the kind of silent bug (a golden question that can never pass
because its expected chunk ID has a typo, quietly rendering that
question's "pass" meaningless) that's cheap to introduce and easy to
miss by eye in a list of 15 frozensets.

### Two small, unrelated documentation bugs found while checking scope

Asked directly whether ARCHITECTURE.md needed updating for this work
(it doesn't touch the graph's shape, so no) — but checking it against
the real code surfaced two pre-existing staleness bugs unrelated to
this slice: the System overview diagram's FastAPI node was missing
`/catalog` (added several slices ago), and the RAG diagram said "~24
SchemaChunks" when the corpus has grown to 35 real chunks. Fixed both,
and also added `catalog.py` as a second box next to `genre_stats.py`
in the System overview diagram, since it bypasses `connection.py` the
same way but had never been drawn — see the entry just above this one.

### Verification

`ruff check src/ tests/`, `uv run mypy src/`, and the full pytest suite
(now 84 tests, up from 83) all clean. The new test itself was run
individually first to confirm it actually exercises real retrieval
code (not a stub), then as part of the full suite to confirm it
composes cleanly with everything else.

### Open questions (new)

- **15 golden questions is a reasonable start, not exhaustive.** Some
  corpus chunks (e.g. `column:owners_high` specifically, distinct from
  `owners_low`) aren't independently tested — the eval currently checks
  clusters of related chunks together rather than every chunk in
  isolation. Worth expanding if the corpus grows significantly or a
  real retrieval miss shows up in production that this set wouldn't
  have caught.
- **The bar is 1.0 with zero slack.** That's honest given what was
  measured, but it also means any future corpus edit that changes even
  one chunk's wording in a way that shifts its embedding slightly could
  fail this test without retrieval actually being "worse" in any way a
  user would notice — an acceptable trade for a portfolio project's
  regression net, but worth knowing if this pattern is reused somewhere
  with a bigger, noisier corpus.

## Slice 23 — Making the retry loop's self-correction visible, and a real bug found in the design pass

**Date:** 2026-08-29

`execute_tools_node` has had a self-correction retry loop since early in
this project (a tool error gets fed back to the model as a `ToolMessage`,
which gets another try, up to `SQL_MAX_RETRIES`). Nothing outside a
debugger could ever see it happen, though — `attempts` lived in internal
graph state only, never reached the API response, a log line, or
anywhere a person could look and answer "how often does this actually
fire, and does it work."

### The distinction that mattered: `attempts` was already overloaded

Read the existing code before adding anything, rather than assuming
`attempts` meant "retries." It doesn't, quite: `execute_tools_node`
increments it once per tool call in the loop, success or failure alike.
A question needing two legitimate tool calls (a lookup, then a stats
call) increments it exactly the same way a single failed-then-retried
call would. Surfacing the existing `attempts` field alone would have
produced a "self-correction rate" that was actually measuring "how many
tool calls did this question need" — a real but different thing.
Added a second, separate counter, `tool_errors`, incremented only
inside the `except` branch that actually catches a failure. This is the
whole point of the feature: without this split, a genuinely useful
multi-step question and an actual model mistake look identical in the
data, and any rate computed from the conflated number would be
meaningless.

### A real correctness bug caught during the design pass, before it shipped

The natural way to report "how many self-corrections actually
recovered" is `runs_with_tool_error - runs_that_hit_the_retry_cap`,
computed from two independently-incremented counters. Working through
it by hand before writing the code: `attempts` can theoretically reach
`SQL_MAX_RETRIES` through a long chain of *successful* tool calls that
never errored at all (rare in this system, but not impossible, and not
excluded by the type system). If that ever happened, `runs_that_hit_the_retry_cap`
would include a run that was never in `runs_with_tool_error` to begin
with, and the subtraction could go negative — an obviously wrong
"recovered" count with no exception ever raised to reveal it, exactly
the kind of bug that ships quietly and shows up as a nonsensical number
on a dashboard months later. Fixed by tracking the actual intersection
directly (`runs_with_tool_error_that_hit_the_attempts_cap`, incremented
only inside the branch that already knows `had_error` is true) instead
of two independent totals subtracted after the fact — a subset by
construction, so the subtraction can never go negative. This is a
correctness bug that never ran, caught by reasoning about the data
model before writing the implementation, not by a failing test after
the fact.

### What deliberately does NOT count toward these stats, verified live

A semantic-cache hit replays a stored `AgentResult` without running the
graph again — counting it would double-count the same underlying run
under a different question's cache key. A hard provider failure (Groq
rate-limited or erroring before the agent ever reaches the tool-call
loop) is a different failure class entirely, not a self-correction
event — the request never got far enough to try or fail a tool call.
Both exclusions were reasoned about in the design, then actually
confirmed live rather than just argued for: rapid manual testing during
verification genuinely triggered a real Groq 413 (tokens-per-minute
limit exceeded, an authentic free-tier constraint, not a contrived
test), which correctly fell through to the existing
`FRIENDLY_ERROR_MESSAGE` 503 path with no change in behavior, and
`/health`'s `total_runs` confirmed unchanged afterward — the exclusion
held under a real failure, not just an imagined one.

### Verification

`tests/test_graph_tool_errors.py`: four new tests directly against
`execute_tools_node`, using the same real-DuckDB-fixture-over-mocking
approach as `test_catalog.py`/`test_genre_stats.py` — including an
actual `DROP TABLE games` to produce a real `UnsafeQueryError`, not a
simulated one. One test specifically encodes the reason this feature
exists: two successful calls in one turn must leave `tool_errors` at
`0`. `ruff check`, `mypy src/`, and the full suite (88 tests, up from
84) all clean.

Also verified end to end against a real running backend, not just unit
tests: confirmed `/health`'s new `self_correction` block and `/ask`'s
`attempts`/`tool_errors` fields are both present and correctly computed
on genuine live Groq round trips (including catching and killing a
stale backend process from an earlier verification session that was
still bound to port 8000 and silently serving pre-Slice-23 responses —
worth remembering: a "field missing" error can mean the code is wrong,
or it can mean you're not actually talking to the code you think you
are).

### Open questions (new)

- **No real self-correction (an actual model-produced SQL error, not a
  hand-crafted one) has been observed live yet.** Every real question
  tried during verification either succeeded on the first attempt or
  hit a hard Groq rate limit before reaching the tool loop at all. The
  mechanism is proven correct at the unit level against a genuine
  error; the end-to-end "a real live mistake gets logged and counted
  correctly" path is inferred from the wiring, not yet observed
  in production traffic.

## A scoping decision, not a slice: dropping the data-analysis case study

**Date:** 2026-08-29

Slice 21's audit had flagged a standalone data-analysis case study (real
EDA and charts over the 1,000-game catalog) as worth adding for a Data
Scientist/Data Analyst reviewer specifically, distinct from this
project's AI-engineering audience. Asked directly whether it was still
worth building, and it isn't: this project is explicitly positioned for
AI Engineer roles, and separate DS/DA portfolio projects already exist
elsewhere covering that audience. Building it here would spend real time
speaking to a reviewer this project was never meant for, at the cost of
time better spent on the AI-engineering-specific items still open (the
README hook, quantified results) or on applying and interview prep
directly. See PLAN.md's "Dropped" section for the entry.

## Slice 24 — Real numbers, published as they actually came out

**Date:** 2026-08-29

The last audit item asked for quantified results: real eval accuracy,
real `/ask` latency, real cost per question, cache hit rate. The
temptation with a slice like this is to run something until it looks
good, then publish that run. Didn't do that — ran the real eval suite
once, with real instrumentation, and published exactly what came back,
including a real failure.

### Verifying Groq's pricing live, not from memory

Cost per question needs a real $/token rate. Checked Groq's current
on-demand pricing for `openai/gpt-oss-120b` live rather than trusting
training data, which can be stale for something that changes as often
as API pricing: $0.15/M input tokens, $0.60/M output tokens. Same
instinct as verifying the Steam CDN URL or Render's free-tier terms
earlier in this project — a factual claim about an external service
gets checked, not assumed.

### Finding the right instrumentation point before touching any code

The real engineering question here was how to get accurate token counts
across a *whole* agent run (router + agent node, possibly several tool-
call rounds) without invasively changing `classify_question()`'s or
`judge_answer()`'s return types just to smuggle usage data out of
`with_structured_output()` calls, which don't normally expose raw token
usage on their parsed Pydantic return value. Tested
`langchain_core.callbacks.get_usage_metadata_callback()` — a contextvar-
based callback that hooks at `on_llm_end`, before structured-output
parsing consumes the raw response — against a real live `run_agent()`
call before trusting it, and confirmed it correctly captured usage from
*every* LLM call in the graph, structured-output router call included,
with zero changes to any existing function signature. Wired it directly
into `run_evals.py` as a permanent addition (not a disposable script),
since it's exactly the kind of thing worth measuring on every eval run
going forward, not just once.

Deliberately excluded the judge's own LLM call from the tracked block:
the judge is eval-harness overhead, not something a real `/ask` caller
ever pays for, so including it would overstate the real per-question
cost.

### The numbers, published as they came out

Route accuracy: 6/6. Deterministic checks: **5/6**, not 6/6 — one real
failure, and a notable one: `analysis_action_vs_f2p_not_mislabeled` is
the exact regression test Slice 4 built specifically to catch a
free-to-play group being mislabeled without actually being filtered to
`price_usd = 0`. On this real run, the model used
`AVG(CASE WHEN price_usd = 0 THEN price_usd END)` directly in raw SQL
instead of calling `run_stats`'s `compare_two_groups` mode, and the
check correctly flagged it. This is the eval harness doing exactly its
job — catching a live instance of a known failure class — not a
disappointing result to explain away. A quieter, more tempting version
of this slice would have re-run the suite until it came back 6/6 and
reported that instead; publishing the real 5/6 is a more honest signal
about what the harness actually catches, and arguably a better one to
be able to discuss in an interview than a suspiciously clean number.

Avg judge score: 4.2/5. Avg latency: 15.5s over 6 real full-graph runs
— reported the actual range (3.2s to 37.1s) alongside the average
rather than let one number imply more precision than 6 samples support;
the slow outlier was an `analysis` question requiring two sequential
LLM turns plus a heavier query. Avg cost per question: **$0.00057** —
real token counts, real pricing, meaning roughly $0.57 to answer 1,000
questions on Groq's on-demand list price.

### The cache-hit finding: honest and more specific than a single number

There's no real production traffic yet to derive an organic cache "hit
rate" from — inventing one would be exactly the kind of fabricated
number this project has refused to do elsewhere (the em-dash guarantee,
the eval ground truth computed live instead of hardcoded). Instead, ran
a real, small, labeled test against a live backend: a genuinely
different question correctly missed (true negative, no false
positives observed in this or any earlier session's testing); a
natural real-world paraphrase — "Which game costs the most out of
everything in the catalog?" against the cached "What is the most
expensive game in the catalog?" — **also missed**, a genuinely useful
finding that the 0.93 similarity threshold (calibrated empirically back
when the cache was built, see `src/config.py`'s own comment on it) is
more conservative in live practice than a casual assumption would
suggest; a near-identical rewording ("the whole catalog" vs "the
catalog") correctly hit, confirmed via the exact `cache hit: ... ~ ...`
log line, not just the response's `cached: true` flag. The honest
takeaway — precise but conservative — is more useful and more credible
than a single invented percentage would have been.

### A real bug found along the way, deliberately not fixed in this slice

`golden_questions.py`'s `forecast_not_supported` question still carries
`reference_facts` text ("This system has no forecasting tool or
time-series data") that was accurate before Slice 9b's real
`run_forecast` tool existed and is stale now — likely part of why that
question scored a middling 3/5 from the judge, which is grading the
real answer against outdated ground truth. Noticed while reading the
report, not fixed here: this slice was about gathering and publishing
numbers honestly, not re-validating the golden set, and conflating the
two would have meant reporting numbers from a suite that changed mid-
measurement. Logged as an open item instead (see PLAN.md's Slice 24
entry).

### A real environment trap, hit twice now

Killed a stale `uvicorn` process during verification whose port was
still bound from an earlier session — the second time this exact thing
has happened in this project (see Slice 23's entry). `pkill -f "uvicorn
src.api.main"` silently reports nothing and does not actually stop the
process in this environment, for reasons not fully diagnosed (likely a
process-tree/shell-wrapper mismatch under `uv run` on Windows Git Bash).
Confirmed via `netstat -ano | grep ":8000"` and killed it precisely with
`taskkill //F //PID <pid>` instead. Worth remembering as a standing
practice for this project specifically, not just this slice: when a
live check shows unexpected/stale data, checking whether you're
actually talking to fresh code is a real, recurring first step here,
not a hypothetical one.

### Verification

`ruff check`, `mypy src/`, and the full pytest suite (88 tests, all
pre-existing — this slice added instrumentation and ran real evals, no
new test file) all clean. The numbers themselves are the verification
artifact for this slice: real Groq calls, real pricing, real timing, a
real cache test against a real running backend, published without
editing.

### Open questions (new)

- **`forecast_not_supported`'s stale reference facts** (above) should
  be rewritten to match the real post-Slice-9b behavior before the next
  time eval numbers are gathered, or it will keep quietly dragging that
  question's judge score down for a reason that has nothing to do with
  actual answer quality.
- **n=6 is a thin sample for latency and cost claims.** The published
  numbers are real and honestly reported, but six questions is enough
  to be directionally right, not enough to treat as a stable production
  average — worth re-measuring at a larger scale before quoting these
  numbers as if they were production telemetry rather than a single
  eval run's honest result.
