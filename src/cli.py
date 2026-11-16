"""Thin CLI shell — argument parsing, presentation, and exit codes.

Business logic lives in `src/bookmark_agent/application/workflows.py`.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv
from openai import AsyncOpenAI

from bookmark_agent.application.workflows import (
    run_batch_download,
    run_batch_upload,
    run_categorization,
    build_bookmark_graph,
)
from bookmark_agent.harness import run_agent
from bookmark_agent.domain.errors import (
    BookmarkAgentError,
    ConfigError,
    NoPendingBatchError,
)
from bookmark_agent.config import load_settings
from bookmark_agent.adapters.sqlite_store import init_db
from bookmark_agent.config import update_setting

from utils.colors import c, colorize, error, header, info, ok, warn

BOOKMARKS_FILE = "bookmarks.md"

load_dotenv()

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)


def get_client() -> AsyncOpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ConfigError("OPENAI_API_KEY is not set")
    # Trace every LLM call in Langfuse when keys are present (self-hosted or cloud);
    # falls back to the plain client so the repo runs without it.
    if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
        from langfuse.openai import AsyncOpenAI as LangfuseAsyncOpenAI
        return LangfuseAsyncOpenAI(api_key=api_key)
    return AsyncOpenAI(api_key=api_key)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Bookmark management system where we batch and update given bookmarks")
    parser.add_argument("-cs", "--current_stage",
                        type=str,
                        choices=["upload", "download", "update", "agent"],
                        help="Run given stage of the program to update the bookmark from batch/fetch/update")
    parser.add_argument('--prompt', type=str,
                        default="Check the current bookmark pipeline state and run whatever stages are needed.",
                        help="Instruction for the agent stage (-cs agent)")
    parser.add_argument('--init-db', nargs='?', const='data', default=None, metavar='FOLDER',
                        help="Create bookmarks.db in FOLDER (default: data) and save its path to config.yaml")
    parser.add_argument("-gbg", "--generate_bookmark_graph",
                        action='store_true',
                        default=False,
                        help="If set, generate and save bookmark graph")
    parser.add_argument('--quiet', action='store_true')
    return parser.parse_args()

async def upload_command(client, config: dict) -> int:
    print(header("Stage: Batch Upload"))
    result = await run_batch_upload(client, config, BOOKMARKS_FILE)

    if not result.submitted:
        print(warn(result.reason or "Upload skipped"))
        return 0

    print(colorize(
        f"Trigger hit! Found {result.total_entries} entries. "
        f"Processing first {result.processed_count}...", c.Y, c.B))
    print(info("Batch Job submitted to OpenAI"))
    print(ok(f"Job ID: {result.job_id}"))
    return 0


async def download_command(client) -> int:
    print(header("Stage: Batch Download"))
    try:
        result = await run_batch_download(client)
    except NoPendingBatchError:
        print(warn("No pending batch jobs found."))
        return 0

    if result.outcome == "completed":
        print(ok(f"Batch job {result.job_id} completed. Results saved to {result.output_path}"))
    elif result.outcome == "failed":
        print(warn(f"Batch job {result.job_id} failed. Error log: {result.error_path}"))
    else:
        print(info(f"Batch job {result.job_id} is still '{result.provider_status}'. Try again later."))
    return 0


async def update_command(client, config: dict) -> int:
    print(header("Stage: Update / Categorize"))
    result = await run_categorization(client, BOOKMARKS_FILE)

    print(ok(f"Resolved {len(result.final_decisions)} bookmark placements"))
    for decision in result.final_decisions:
        placement = f"{decision.get('path', '?')}#{decision.get('section', '?')}"
        print(info(f"  {decision.get('id', '?')} -> {placement}"))
    return 0


async def agent_command(client, config: dict, prompt: str) -> int:
    print(header("Stage: Agent Harness"))
    answer = await run_agent(prompt, client, config)
    print(ok(answer or "Agent finished with no answer."))
    return 0


def graph_command(config: dict) -> int:
    print(header("Generating Bookmark Graph"))
    inserted = build_bookmark_graph(config)

    for name, count in inserted.items():
        print(info(f"Inserted {name} with {count} entries."))
    print(ok(f"Graph saved with {len(inserted)} files."))
    return 0

EXIT_OK = 0
EXIT_PIPELINE_ERROR = 1
EXIT_CONFIG_ERROR = 2
EXIT_INTERRUPTED = 130


async def dispatch(args, client, config: dict) -> int:
    if args.generate_bookmark_graph:
        code = graph_command(config)
        if args.current_stage is None:
            return code

    if args.current_stage == "upload":
        return await upload_command(client, config)
    if args.current_stage == "download":
        return await download_command(client)
    if args.current_stage == "update":
        return await update_command(client, config)
    if args.current_stage == "agent":
        return await agent_command(client, config, args.prompt)

    return EXIT_OK


def init_db_command(folder: str) -> int:
    try:
        db_file = init_db(folder)
    except FileExistsError as exc:
        print(warn(str(exc)))
        return EXIT_PIPELINE_ERROR
    update_setting("db_path", db_file)
    print(ok(f"Database created at {db_file} (saved to config.yaml)"))
    return 0


def main() -> int:
    args = parse_args()

    # init-db runs before load_settings: a fresh clone may have no config.yaml yet
    if args.init_db is not None:
        return init_db_command(args.init_db)

    log_level = logging.WARNING if args.quiet else logging.DEBUG
    logging.basicConfig(level=log_level, format='%(message)s')

    try:
        config = load_settings()
        client = get_client()
        if args.current_stage:
            print(f"Running stage: {args.current_stage}")
        return asyncio.run(dispatch(args, client, config))
    except ConfigError as exc:
        print(error(f"Configuration error: {exc}"))
        return EXIT_CONFIG_ERROR
    except BookmarkAgentError as exc:
        print(error(f"Pipeline error: {exc}"))
        return EXIT_PIPELINE_ERROR
    except KeyboardInterrupt:
        print(warn("Interrupted by user"))
        return EXIT_INTERRUPTED
    finally:
        # short-lived CLI: send buffered Langfuse traces before exit
        try:
            from langfuse import get_client as langfuse_get_client
            langfuse_get_client().flush()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
