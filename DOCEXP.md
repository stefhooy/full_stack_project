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
