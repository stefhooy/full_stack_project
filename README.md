# AI Game Analyst

[![Tests](https://github.com/stefhooy/full_stack_project/actions/workflows/test.yml/badge.svg)](https://github.com/stefhooy/full_stack_project/actions/workflows/test.yml)
[![Frontend CI](https://github.com/stefhooy/full_stack_project/actions/workflows/frontend-ci.yml/badge.svg)](https://github.com/stefhooy/full_stack_project/actions/workflows/frontend-ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)
![Next.js 16](https://img.shields.io/badge/next.js-16-black.svg)

**[Try it live](https://full-stack-project-sepia-nine.vercel.app)**, ask a
real question about the video game market and watch it write the SQL
itself. (Free-tier host; the first request after a quiet stretch can take
up to a minute to wake back up.)

Most portfolio AI agents are a system prompt wrapped around a chat UI.
This one writes and runs real SQL against a database it built itself,
corrects its own tool-call errors when they actually happen, and reports
its own measured accuracy, retrieval quality, and per-question cost,
numbers you can check yourself below, not claims asking to be taken on
faith.

![Ludo answering a real question live, with the exact SQL it wrote and the schema it retrieved shown below the answer](docs/live-demo.png)

Built as a series of thin, working vertical slices; this snapshot is
through **Slice 43** (see [PLAN.md](PLAN.md) for the full roadmap,
[ARCHITECTURE.md](ARCHITECTURE.md) for a diagram-first tour of the current
system, and [DOCEXP.md](DOCEXP.md) for the full engineering log).

## Tech stack

### Languages

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white)

### AI / Agent

![LangChain](https://img.shields.io/badge/LangChain-1C3C3C?style=for-the-badge&logo=langchain&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-1C3C3C?style=for-the-badge&logo=langgraph&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-F55036?style=for-the-badge&logo=groq&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-000000?style=for-the-badge&logo=ollama&logoColor=white)
![SciPy](https://img.shields.io/badge/SciPy-8CAAE6?style=for-the-badge&logo=scipy&logoColor=white)
![NumPy](https://img.shields.io/badge/NumPy-013243?style=for-the-badge&logo=numpy&logoColor=white)

### Data

![DuckDB](https://img.shields.io/badge/DuckDB-FFF000?style=for-the-badge&logo=duckdb&logoColor=black)
![Pydantic](https://img.shields.io/badge/Pydantic-E92063?style=for-the-badge&logo=pydantic&logoColor=white)

### Backend

![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)

### Frontend

![Next.js](https://img.shields.io/badge/Next.js-000000?style=for-the-badge&logo=nextdotjs&logoColor=white)
![React](https://img.shields.io/badge/React-149ECA?style=for-the-badge&logo=react&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-06B6D4?style=for-the-badge&logo=tailwindcss&logoColor=white)
![Motion](https://img.shields.io/badge/Motion-0055FF?style=for-the-badge&logo=framer&logoColor=white)
![Recharts](https://img.shields.io/badge/Recharts-22B5BF?style=for-the-badge&logo=recharts&logoColor=white)
![Three.js](https://img.shields.io/badge/Three.js-000000?style=for-the-badge&logo=threedotjs&logoColor=white)

### Tooling and CI/CD

![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?style=for-the-badge&logo=githubactions&logoColor=white)
![pytest](https://img.shields.io/badge/pytest-0A9EDC?style=for-the-badge&logo=pytest&logoColor=white)
![ESLint](https://img.shields.io/badge/ESLint-4B32C3?style=for-the-badge&logo=eslint&logoColor=white)
![Ruff](https://img.shields.io/badge/Ruff-D7FF64?style=for-the-badge&logo=ruff&logoColor=black)
![uv](https://img.shields.io/badge/uv-DE5FE9?style=for-the-badge&logo=uv&logoColor=white)
![Render](https://img.shields.io/badge/Render-46E3B7?style=for-the-badge&logo=render&logoColor=white)
![Vercel](https://img.shields.io/badge/Vercel-000000?style=for-the-badge&logo=vercel&logoColor=white)
![MCP](https://img.shields.io/badge/Model_Context_Protocol-000000?style=for-the-badge&logo=modelcontextprotocol&logoColor=white)

`mypy` and `sqlglot` (the real SQL parser behind the safety guard) round
out the backend but don't have their own badge icons.

## AI Engineer Features

- **Agentic tool use with a measured self-correction rate, not a claim.**
  The agent (`router` &rarr; `retrieve_schema` &rarr; `agent` &harr;
  `execute_tools` &rarr; `build_chart_spec`, see
  [ARCHITECTURE.md](ARCHITECTURE.md)) retries its own tool errors up to 3
  times, and `attempts`/`tool_errors` are real counters, surfaced per
  request and aggregated live at `/health` as `self_correction`, not a
  one-off screenshot of it working once.
- **RAG with retrieval quality that's measured, not assumed.** Schema
  chunks are embedded and retrieved per question instead of always
  stuffing the whole schema into the prompt, and a hand-labeled recall@k
  eval gates that in CI, currently **1.000 recall at production's real
  top-k**.
- **A real eval harness, running in CI, not just on my machine.** A golden
  question set with ground truth computed live from the database,
  deterministic checks, and an LLM-as-judge pass, with a real exit code,
  runs daily and on demand in GitHub Actions. When one of those checks was
  itself found to be wrong (testing which tool ran instead of whether the
  answer was correct), that bug hunt is written up in full rather than
  quietly fixed, see the Measured results section below.
- **Real cost and token accounting, not an after-the-fact estimate.**
  Every `/ask` response reports its own `total_tokens` and
  `estimated_cost_usd` (Groq's actual live on-demand pricing), logged per
  request and aggregated at `/health` as `usage`.
- **Honest about limits, by design.** The forecast tool reports
  "insufficient history" instead of fabricating a number when a game's
  live player-count history is too young to project from, and
  self-upgrades to a real linear-trend projection the moment enough
  history exists, no code changes needed. The semantic cache's precision
  was checked live against real paraphrases rather than assumed.
- **The same guarded tools, exposed two real ways.** A web app for humans,
  and an MCP server (`src/mcp_server/`) exposing the identical
  `run_sql`/`run_stats` implementations to Claude Desktop, Claude Code, or
  Cursor, one safety boundary, not two implementations to keep in sync.

## Measured results

Real numbers from a real run of `python -m src.evals.run_evals` against
the golden question set, real Groq token usage, and Groq's actual current
on-demand pricing, published as they came out, not re-run until clean.
This suite also runs automatically in CI, daily and on demand
(`.github/workflows/run_evals.yml`). See DOCEXP.md's Slice 24/27/30/36
entries for full methodology and caveats.

| Metric | Result |
|---|---|
| Route accuracy | 5/5 |
| Deterministic checks | 5/5 |
| Avg LLM-judge score | 4.2/5 |
| Avg `/ask` latency | 13.3s (n=5, real full-graph runs) |
| Avg cost per question | $0.00066 (Groq on-demand list price) |
| RAG retrieval recall@8 | 1.000 (15 hand-labeled questions) |

Worth being honest about how this got to 5/5: earlier versions of this
table showed a real, repeated 4/5 and described it as the same model bug
recurring. That framing was wrong. Investigating it properly found the
failing check itself was testing which tool the model used, not whether
its answer was correct, so a genuinely right answer via plain SQL instead
of the expected tool got marked as a failure every time. Fixed the check
to verify the real returned value regardless of which tool produced it,
then confirmed the fix for real in CI (fresh runner, freshly built
catalog), not just locally. Full writeup in DOCEXP.md's Slice 30 and 36
entries, including the earlier, wrong framing, left visible rather than
edited away.

## Quickstart

Dependencies are managed with [uv](https://docs.astral.sh/uv/). Always
include `--extra agent`, a bare `uv sync` installs only the lean
ingestion/db base set and will actively uninstall FastAPI/LangGraph/scipy
if they're already there, see `pyproject.toml`'s comments for why the
split exists.

```bash
uv sync --extra agent
cp .env.example .env
# then set GROQ_API_KEY (free tier: https://console.groq.com/keys)
```

```bash
python -m src.ingestion.ingest      # one-time; builds the local DuckDB catalog (a few minutes)
uvicorn src.api.main:app --reload   # serves the API
```

```bash
curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the 5 most-owned free-to-play games?"}'
```

Try a lookup ("Which game has the highest peak concurrent player
count?"), an analysis ("Is the price difference between Action games and
other games statistically significant?", a real `run_stats` p-value), a
forecast ("How many players will Counter-Strike 2 have next month?",
honest about insufficient history for most games right now), or a
deliberately vague one ("Is this game good?", the agent asks which game
instead of guessing). The response includes the SQL actually run, the raw
rows, and which RAG-retrieved schema chunks were used, so retrieval is
visible, not asserted.

**Frontend** (separate terminal, backend must already be running):

```bash
cd frontend
cp .env.local.example .env.local
npm install
npm run dev
```

Open http://localhost:3000. See [frontend/README.md](frontend/README.md)
for the UI itself (a dark, neon-green identity; a real film-strip hero of
live Steam cover art; a genre browser; charts; a step-by-step "show the
work" trace).

**Tests** (88 pytest tests, real DuckDB fixtures, no mocks of this
project's own DB layer; needs the `dev` extra):

```bash
uv sync --extra agent --extra dev
uv run pytest -v
```

Runs on every push/PR via `.github/workflows/test.yml`, alongside `ruff`
and `mypy`. See [PLAN.md](PLAN.md) for what else exists (an eval suite you
can run yourself with `python -m src.evals.run_evals`, an optional
live-player-count poller, and more).

## Architecture

A LangGraph agent: `router` classifies each question (lookup / analysis /
forecast / needs-clarification) with structured LLM output before any
database work happens, then `retrieve_schema` &rarr; `agent` &harr;
`execute_tools` &rarr; `build_chart_spec` runs a real, hand-written
tool-calling loop with self-correction, not a prebuilt agent constructor.
Every SQL query passes through a read-only, guarded connection enforced
by a real SQL parser, independent of whatever the prompt told the model
to do. Full diagrams, the node-by-node walkthrough, and the design
choices worth defending are in [ARCHITECTURE.md](ARCHITECTURE.md).

## MCP server

`src/mcp_server/server.py` exposes `run_sql` and `run_stats`, the exact
same guarded implementations the LangGraph agent uses, to any
MCP-compatible AI app. Free to run: local stdio transport, no hosting, no
LLM API key needed (the calling app supplies its own model).

```bash
uv run mcp dev src/mcp_server/server.py   # smoke test with the official MCP Inspector
```

**Claude Code:**

```bash
claude mcp add ai-game-analyst -- uv run --directory "C:\path\to\full_stack_project" python -m src.mcp_server.server
```

**Claude Desktop** (`%APPDATA%\Claude\claude_desktop_config.json` on
Windows):

```json
{
  "mcpServers": {
    "ai-game-analyst": {
      "command": "uv",
      "args": ["run", "--directory", "C:\\path\\to\\full_stack_project", "python", "-m", "src.mcp_server.server"]
    }
  }
}
```

Requires the database to already exist (`python -m src.ingestion.ingest`
first).

## Deploying

**Live since Slice 19:** backend on
[Render](https://ai-game-analyst-api.onrender.com) (free tier, Docker),
frontend on [Vercel](https://full-stack-project-sepia-nine.vercel.app)
(Hobby). A normal Python host for the backend rather than Vercel Python
functions, deliberately, this stack's real footprint (an ONNX embedding
model, scipy, a DuckDB file, multi-step LLM calls that can run 10 to 30
seconds) doesn't comfortably fit serverless limits.

Full setup steps, environment variables, and the caveats worth knowing
(in-memory cache and rate limiter, Render's free-tier cold-start
behavior, keeping data fresh via scheduled GitHub Actions) are in
DOCEXP.md's Slice 19 entry and the workflow files themselves
(`.github/workflows/poll_player_counts.yml`,
`.github/workflows/refresh_catalog.yml`).

## More

- [PLAN.md](PLAN.md), the full slice-by-slice roadmap, including what was
  considered and dropped
- [ARCHITECTURE.md](ARCHITECTURE.md), a diagram-first tour of the current
  system and the design choices worth defending
- [DOCEXP.md](DOCEXP.md), the full engineering log: what broke, what got
  tried, what surprised me, including the mistakes
- [frontend/README.md](frontend/README.md), the UI in detail
