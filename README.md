# Bookmark Agent — From LLM Pipeline to Agent Harness

A bookmark organizer that began as a **fixed three-stage LLM pipeline** (you picked the stage, the code ran it) and is now an **agent harness**: an LLM agent looks at your request and the pipeline state, and decides itself which workflows to run — calling the project's real functions as tools, including exploring the bookmark tree on its own.

## The Journey

### v1 — LLM-assisted pipeline (`llm-assisted-pipeline` tag)

The original design was a deterministic, human-driven pipeline. Each stage was invoked explicitly via CLI flags (`-cs upload|download|update`):

```
bookmarks.md → [Stage 1: upload]   → OpenAI Batch API → SQLite job store
             → [Stage 2: download] → Retrieve summaries → Persist results
             → [Stage 3: update]   → Jev gate → multi-agent deliberation → placements
```

The intelligence was inside stage 3: a confidence-gated Jev classifier handled easy placements, and ambiguous ones escalated to a taxonomy/similarity/critic deliberation with two rounds plus a coordinator. But the *orchestration* was fixed — you decided which stage ran, and the classification agents received the entire bookmark tree stuffed into every prompt.

That full design, including the consensus protocol, compensating transactions, and configuration, is preserved in **[README_OLD_PIPELINE.md](./README_OLD_PIPELINE.md)** — read it if you want the complete detail of how the old pipeline worked. The git tag **`llm-assisted-pipeline`** marks the last commit of that era:

```bash
git checkout llm-assisted-pipeline      # see the repo as it was, pipeline-only
```

### v2 — Agent harness (`agent-harness` tag)

The inversion: instead of a human running stages, an **agent loop** owns the orchestration. The existing workflows weren't rewritten — they were exposed as **tools**. The agent inspects tool results after every call and decides the next step itself.

## How It Works Now

```
your prompt ──► agent loop (src/bookmark_agent/harness.py)
                    │  model decides, calls tools:
                    │
                    ├── build_bookmark_graph     → rebuild tree cache from config.yaml
                    ├── upload_bookmarks_batch   → submit OpenAI summarization batch
                    ├── check_and_download_batch → poll & download batch results
                    ├── categorize_bookmarks     → Jev gate + multi-agent deliberation
                    └── list_bookmark_sections   → explore the tree (path#section, counts,
                                                   example titles) instead of receiving
                                                   the whole tree in the prompt
                    │
                    ▼  results (or errors) fed back as tool messages
                    ▼  loop repeats until the agent answers without calling a tool
```

Key properties:

- **The agent decides.** "Process whatever is pending" or "where would this ML article go?" — the agent figures out which stages are needed from the tool results.
- **Tree exploration via tool calls.** The agent calls `list_bookmark_sections` to see the taxonomy itself rather than having the full tree baked into its prompt.
- **Errors are results, not crashes.** A failed tool (no tree yet, no pending batch) returns `{"error": ...}` to the agent, which can recover — e.g. build the graph first, then categorize.
- **Turn-capped loop.** `MAX_TURNS = 10` bounds any single run.
- **All v1 workflows reused unchanged** — the harness adds no new bookmark functionality, only the agent loop and tool schemas.

## Usage

```bash
# Agent mode — describe what you want; the agent picks the tools
python cli.py -cs agent --prompt "Check the pipeline state and run whatever is needed"

# Targeted example: let the agent explore the tree and answer
python cli.py -cs agent --prompt "Which sections exist for AI topics, and how full are they?"

# The original stages still work exactly as before
python cli.py -cs upload
python cli.py -cs download
python cli.py -cs update
```

Environment: `OPENAI_API_KEY` (workflows/agent loop) and `OPENROUTER_PRJ_API_KEY` (Jev classifier), plus a `config.yaml` (see [README_OLD_PIPELINE.md](./README_OLD_PIPELINE.md) for its shape).

## Project Structure

```
src/
├── cli.py                          # CLI shell — stages + agent mode entry point
├── bookmark_agent/
│   ├── harness.py                  # NEW: tool schemas + agent decision loop
│   ├── application/workflows.py    # The pipeline stages (now exposed as tools)
│   ├── agents/                     # Jev gate, deliberation rounds, coordinator
│   ├── domain/                     # Bookmark tree, errors
│   └── adapters/                   # Markdown, OpenAI batch, SQLite, URL fetcher
├── models/, utils/                 # Shared models and helpers
tests/
└── test_harness.py                 # Self-checks: loop wiring, tree tool, error feedback
```

## Self-Checks

```bash
python tests/test_harness.py   # no network, no API key needed
```

## To Do

- [ ] Fix `proposal['title']` access in `parse_agent_discussion`/coordinator — `AgentProposal` has no `title` field (the harness surfaces this as an agent-visible error today)
- [ ] Carry-over goals from v1: SQLite as source of truth, batch/fetch hint merging, subsection-split flow

## Learn

- Wrapping existing functions as tools is the cheapest path from "pipeline" to "agent harness" — zero orchestration logic was rewritten.
- Feeding errors back as tool results turns broken callees into agent-recoverable situations instead of crashes.
