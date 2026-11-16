"""LLM harness: an agent decides which existing workflows to run, via tool calls.

No new bookmark functionality lives here — every tool wraps an existing
workflow in `bookmark_agent.application.workflows` or an existing tree helper.
The loop feeds each tool result back so the agent decides the next step itself.
"""

import json
import logging
from dataclasses import asdict

from bookmark_agent.application import workflows
from bookmark_agent.domain.bookmark_tree import load_tree
from utils.tree_helpers import candidate_sections

logger = logging.getLogger(__name__)

MODEL = "gpt-4o-mini"
# shortcut: only a turn cap, no token/cost budget; add one if runs get expensive
MAX_TURNS = 10

SYSTEM_PROMPT = """You orchestrate a bookmark organization pipeline. State you act on:
- bookmarks.md: unprocessed bookmark entries.
- SQLite store: OpenAI batch summarization jobs (pending/completed).
- Bookmark tree cache: the taxonomy of files and sections bookmarks are placed into.

Call tools to inspect state and run the real workflows; results come back to you.
When the request is fulfilled (or nothing needs doing), answer the user in plain
text without calling any more tools."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "build_bookmark_graph",
            "description": "Rebuild the bookmark tree cache from the files in config.yaml. Needed before categorizing if no tree exists yet.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upload_bookmarks_batch",
            "description": "Fetch article content for new bookmarks.md entries and submit an OpenAI batch summarization job. Returns submitted=False with a reason if fewer entries than the configured batch_size.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_and_download_batch",
            "description": "Check the oldest pending batch job and download its results if completed. Returns completed, failed, or in_progress.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "categorize_bookmarks",
            "description": "Run the categorization pipeline (Jev classifier, then multi-agent discussion) over processed summaries and return final path#section placements.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_entries": {
                        "type": "integer",
                        "description": "Limit how many bookmarks to categorize.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "init_db",
            "description": "Create the SQLite batch-job store (bookmarks.db) in a folder (default: data) and save its path to config.yaml. Refused if the db already exists. Needed before upload if no store is set up.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "description": "Folder for the db file. Defaults to 'data'.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_bookmark_sections",
            "description": "List every path#section in the bookmark tree with entry counts and example titles, so placements can be inspected and verified.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


async def execute_tool(name: str, args: dict, client, config: dict) -> dict:
    """Run one tool by name. Errors are returned as results so the agent can recover."""
    try:
        if name == "build_bookmark_graph":
            return {"files_inserted": workflows.build_bookmark_graph(config)}
        if name == "upload_bookmarks_batch":
            return asdict(await workflows.run_batch_upload(client, config))
        if name == "check_and_download_batch":
            return asdict(await workflows.run_batch_download(client))
        if name == "categorize_bookmarks":
            result = await workflows.run_categorization(client, **args)
            return {"final_decisions": result.final_decisions}
        if name == "init_db":
            from bookmark_agent.adapters.sqlite_store import init_db
            from bookmark_agent.config import update_setting
            db_file = init_db(args.get("folder") or "data")
            update_setting("db_path", db_file)
            return {"db_path": db_file}
        if name == "list_bookmark_sections":
            tree_path = config.get("stored_bookmark_graph_path")
            if not tree_path:
                raise ValueError("config.yaml must define stored_bookmark_graph_path")
            return candidate_sections(load_tree(tree_path))
        raise ValueError(f"Unknown tool: {name}")
    except Exception as exc:
        logger.exception("Tool %s failed", name)
        return {"error": str(exc)}


async def run_agent(prompt: str, client, config: dict) -> str:
    """Run the agent loop until it answers without calling a tool."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    for _ in range(MAX_TURNS):
        # visibility of context size, tool called and cost
        response = await client.chat.completions.create(
            model=MODEL, messages=messages, tools=TOOLS, tool_choice="auto"
        )
        message = response.choices[0].message
        messages.append(message)
        if not message.tool_calls:
            return message.content or ""
        for call in message.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            logger.info("Agent tool call: %s(%s)", call.function.name, args)
            result = await execute_tool(call.function.name, args, client, config)
            logger.info("Agent tool result: %s", json.dumps(result, default=str)[:500])
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result, default=str),
            })
    return "Reached the tool-call turn limit without a final answer."
