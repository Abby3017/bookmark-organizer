# Bookmark Agent — LLM-Assisted Bookmark Organizer

A bookmark management system that ingests raw bookmarks from a Markdown file, enriches them through the OpenAI Batch API, and routes them to the correct category file through a confidence-gated, multi-stage LLM deliberation pipeline.

## Architecture Overview

The system is built around a **three-stage pipeline**, each stage independently runnable via CLI flags (`-cs upload|download|update`):

```
bookmarks.md  →  [Stage 1: Batch]  →  OpenAI Batch API  →  SQLite job store
                     ↓
              [Stage 2: Fetch]  →  Retrieve summaries  →  Persist results
                     ↓
              [Stage 3: Update]  →  LLM deliberation  →  Append to category file
```

### Stage 1 — Batch Upload (`upload`)

- Parses new entries from `bookmarks.md`.
- Fetches article content for each URL concurrently (`asyncio.gather`).
- Builds a JSONL batch request file and submits it to the OpenAI Batch API.
- Records the job (`job_id`, file path, status) in a SQLite database for later retrieval.
- Clears processed bookmarks from the source file.

### Stage 2 — Fetch Results (`download`)

- Polls the SQLite job store for pending batch jobs.
- Downloads completed summaries and enrichment data from OpenAI.
- Persists results locally for the decision stage.

### Stage 3 — Update / Categorize (`update`)

- Feeds each bookmark and its summary into a **role-specialized LLM evaluation** workflow.
- The evaluators use up to **2 deliberation rounds** to converge on the best target folder, file, and section.
- Appends the bookmark to the resolved category file. Bookmarks are **append-only** — never overwritten.

## Multi-Stage LLM Decision Framework

The categorization pipeline uses a **confidence-gated, cost-aware decision architecture**. A lightweight Jev classifier handles high-confidence cases, while a proposal–critique–arbitration workflow is used as a targeted escalation path for ambiguous bookmarks. This workflow is inspired by actor–critic separation, but is implemented as structured LLM deliberation rather than reinforcement learning.

### Decision Routing

Jev evaluates each bookmark against the existing set of valid `path#section` candidates and returns a selected placement with a confidence score.

- Classifications with confidence **greater than or equal to 0.80** are accepted directly.
- Classifications below the threshold are escalated to the actor–critic workflow.
- This cascade reduces unnecessary model calls while preserving deeper deliberation for uncertain decisions.

```text
Bookmark
  │
  ▼
Jev classifier
  │
  ├── confidence >= 0.80 ──► Accept classification
  │
  └── confidence < 0.80 ───► Proposal–critique workflow
                       │
                       ├── Round 1: independent proposals
                       ├── Round 2: peer review and revision
                       └── Coordinator: final arbitration
```

### Proposal–Critique–Arbitration Roles

The fallback workflow uses role-specialized LLM evaluators with different optimization objectives. Separating proposal generation, critical review, and arbitration reduces reliance on a single model judgment and makes each decision easier to inspect.

| Component | Responsibility | Optimization Target |
|-----------|----------------|---------------------|
| **Taxonomy evaluator** | Maps the bookmark to a structurally valid file and section in the bookmark tree | Structural fit |
| **Similarity evaluator** | Compares the bookmark with semantically related existing entries | Semantic consistency |
| **Critic evaluator** | Challenges weak, ambiguous, or invalid placements and surfaces alternatives | Precision and risk reduction |
| **Coordinator model** | Reviews the evidence and selects the final placement when disagreement remains | Final decision quality |

### Consensus Protocol

1. **Jev classification** — Selects one candidate path and section from the known taxonomy and records confidence and probability data.
2. **Round 1: independent deliberation** — The Taxonomy, Similarity, and Critic evaluators independently propose a path, section, title, tags, reasoning, and optional subsection split.
3. **Agreement check** — If all evaluators select the same path and section, the result is accepted without another model call.
4. **Round 2: peer review** — For disagreements, each evaluator receives the other evaluators' proposals and may revise or defend its original decision.
5. **Coordinator arbitration** — If disagreement remains, the Coordinator model reviews the bookmark, tree, and both discussion rounds before selecting one final proposal.
6. **Audit persistence** — Jev results, evaluator proposals, revisions, and coordinator decisions are persisted for debugging, evaluation, and future threshold calibration.

### Engineering Characteristics

- **Confidence-gated routing** to control cost and latency.
- **Role specialization** to reduce correlated model errors.
- **Taxonomy-constrained decisions** to prevent invented paths or sections.
- **Structured outputs** validated with Pydantic schemas.
- **Concurrent evaluator execution** using `asyncio` where calls are independent.
- **Deterministic phase transitions** based on explicit agreement checks.
- **Graceful escalation** when confidence is insufficient or proposals conflict.
- **Auditable decision traces** for operational debugging and offline evaluation.

This design treats the classifier as the inexpensive default path and the proposal–critique–arbitration workflow as a deliberate escalation mechanism for genuinely ambiguous bookmarks.

### Section Splitting

When a target section accumulates **30+ entries**, the evaluators are instructed to propose a `subsection_split` — 2–4 concise subsection names — to keep files navigable.

## Configuration

Runtime behavior is controlled by `config.yaml`:

```yaml
batch_size: 5
llm_model: "gpt-4o"
temperatures: [0.2, 0.6, 0.8]   # critic, synthesis, researcher
bookmark:
  learn:
    concept:
      lld: "/path/to/lld/resources.md"
      system_design: "/path/to/system_design/resources.md"
    # ...additional category mappings
```

## Project Structure

```
bookmark_agent/
├── config.yaml              # Batch size, model, temperatures, category paths
├── bookmarks.md             # Input file for new bookmarks
├── requirements.txt
├── src/
│   ├── cli.py               # CLI supported root entry point
│   ├── models/
│   │   └── article_summary.py # Shared article-summary models
│   ├── utils/                # Shared, provider-independent helpers
│   │   ├── colors.py         # Terminal output formatting
│   │   └── tree_helpers.py   # Bookmark-tree serialization helpers
│   ├── bookmark_agent/
│   │   ├── domain/           # Core domain models and bookmark-tree logic
│   │   │   └── bookmark_tree.py
│   │   ├── application/      # Use-case orchestration; currently reserved for future workflows
│   │   ├── agents/           # LLM prompts, calls, Jev routing, and deliberation
│   │   │   ├── agents.py     # Proposal schemas and Chat Completions calls
│   │   │   ├── discussion.py # Round 1, Round 2, and coordinator workflow
│   │   │   └── jev_classifier.py # Jev path/section classification gate
│   │   └── adapters/         # External systems and persistence adapters
│   │       ├── markdown_parser.py # Bookmark Markdown parsing
│   │       ├── openai_batch.py    # OpenAI Batch API integration
│   │       ├── sqlite_store.py    # SQLite persistence adapter
│   │       └── url_fetcher.py     # Article and URL fetching
├── data/                    # Batch request JSONL files + processed results
├── discussions/             # Persisted round and coordinator decision logs
├── organized/               # Output — categorized bookmark files
├── harness/                 # Manual experiments and model comparisons
├── evaluation/              # Evaluation datasets, metrics, and reports
└── docs/                    # Design and project documentation
```

## Organized Bookmarks

This folder contains the final, categorized bookmarks. Each file is named after a category (e.g., `tech.md`, `learning.md`).

- Bookmarks are **appended and never overwritten**.
- Files are structured with section headings for navigability.
- Sections exceeding 30 entries are split into subsections by the evaluators.

## Usage

```bash
# Stage 1: Submit bookmarks to OpenAI Batch API
python main.py -cs upload

# Stage 2: Fetch completed batch results
python main.py -cs download

# Stage 3: Run LLM deliberation and write to category files
python main.py -cs update
```

## Design Principles

- **Separation of concerns** — Each stage is independently runnable and idempotent.
- **Auditability** — Every evaluator decision is logged to `discussions/` and `decision_log` for review.
- **Cost efficiency** — Uses the OpenAI Batch API (50% cost reduction vs. real-time) for summarization, while deliberation is reserved for uncertain classifications.
- **Append-only writes** — Source-of-truth files are never mutated; bookmarks only get added.
- **Concurrency-first** — Article fetching and independent evaluator calls use `asyncio` for throughput.
- **Compensating transactions** — Batch upload uses a logical rollback strategy across OpenAI and SQLite, cancelling the remote batch and deleting uploaded input files if persistence fails. The local JSONL request file is intentionally preserved as an audit artifact, while cleanup failures are logged without masking the original exception.

## To Do

- [x] Add explicit schema for every LLM Output
- [x] Make batch upload operation based on compensating transaction
- [ ] Move storage to sqlite for easier section split and one place of truth
- [ ] Try other LLM agreement methods to evaluate performance

## Bookmark Architecture

## Issues or Fix

1. earlier asking model to give output in json format was not working as expected. So giving it a explicit schema.

## To Do

1. move design storage to sqlite3 which is source of truth and can be queried for future decisions
2. try other LLM decision and evaluation methods to improve bookmark categorization
3. IMP: merge batch output and fetch output to know which url we are getting the hint and tags too.
4. How to handle the split suggestions -- need another flow for that
5. move the processed file to different folder after doing the fetch and download thing 

## Learn

1. complete the OpenAI API integration while completing this project.