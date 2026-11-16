"""Application workflows — orchestrate adapters without presentation logic.

These functions are intentionally free of `print` and CLI concerns so they can
be reused from the CLI, tests, or a future scheduler/API. Each workflow returns
plain data structures describing the outcome; presentation lives in `src/cli.py`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List

from bookmark_agent.adapters.markdown_parser import (
    parse_bookmarks_file,
    parse_processed_bookmarks,
)
from bookmark_agent.adapters.openai_batch import (
    BatchSubmission,
    create_and_upload_bookmark_summaries_batch,
)
from bookmark_agent.adapters.sqlite_store import (
    create_batch_job_entry,
    get_batch_with_given_status,
    update_batch_job_status,
)
from bookmark_agent.adapters.url_fetcher import fetch_article_text
from bookmark_agent.agents.discussion import orchestrate_discussion
from bookmark_agent.domain.bookmark_tree import (
    BookmarkTree,
    extract_bookmark_files,
)
from bookmark_agent.domain.errors import (
    BatchUploadError,
    ConfigError,
    NoPendingBatchError,
)
from utils.batch_request import download_batch_file, retrieve_batch_job


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BatchUploadResult:
    """Outcome of the batch upload workflow."""

    submitted: bool
    total_entries: int
    processed_count: int = 0
    job_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class BatchDownloadResult:
    """Outcome of the batch download workflow."""

    job_id: str
    outcome: str  # "completed" | "failed" | "in_progress"
    output_path: str | None = None
    error_path: str | None = None
    provider_status: str | None = None


@dataclass(frozen=True)
class UpdateResult:
    """Outcome of the categorization workflow."""

    final_decisions: List[dict] = field(default_factory=list)

async def run_batch_upload(
    client,
    config: dict,
    bookmarks_file: str = "bookmarks.md",
) -> BatchUploadResult:
    """Fetch article content and submit a summarization batch job."""
    batch_size = int(config.get("batch_size", 10))

    entries, batch_hint = parse_bookmarks_file(bookmarks_file)
    if len(entries) < batch_size:
        return BatchUploadResult(
            submitted=False,
            total_entries=len(entries),
            reason=(
                f"Insufficient entries: found {len(entries)}, "
                f"need {batch_size}"
            ),
        )

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    file_path = f"./data/batch_requests_{timestamp}.jsonl"
    batch = entries[:batch_size]
    submission: BatchSubmission | None = None

    try:
        article_texts = await asyncio.gather(
            *(
                fetch_article_text(entry.url, str(entry.id))
                for entry in batch
                if entry.id is not None
            )
        )
        submission = await create_and_upload_bookmark_summaries_batch(
            article_texts, client, file_path
        )
        batch_job = submission.batch_job

        create_batch_job_entry(
            {
                "job_id": batch_job.id,
                "file_path_read": file_path,
                "batch_object_details": batch_job.model_dump_json(),
                "status": "pending",
            }
        )

        return BatchUploadResult(
            submitted=True,
            total_entries=len(entries),
            processed_count=len(batch),
            job_id=batch_job.id,
        )
    except asyncio.CancelledError:
        await _compensate_batch_submission(client, submission, file_path)
        raise
    except Exception as exc:
        await _compensate_batch_submission(client, submission, file_path)
        raise BatchUploadError(
            f"Batch upload failed for {len(batch)} bookmarks: {exc} "
            f"(request file preserved at {file_path})"
        ) from exc


async def _compensate_batch_submission(
    client,
    submission: BatchSubmission | None,
    local_file_path: str,
) -> None:
    """
    Best-effort cleanup after a partially completed submission.

    The local JSONL is intentionally preserved as an audit artifact. Remote
    resources are cancelled/deleted when their IDs are available.
    """
    if submission is None:
        return

    try:
        await client.batches.cancel(submission.batch_job.id)
    except Exception:
        logger.exception(
            "Failed to cancel remote batch job %s",
            submission.batch_job.id,
        )

    try:
        await client.files.delete(submission.input_file_id)
    except Exception:
        logger.exception(
            "Failed to delete uploaded batch file %s",
            submission.input_file_id,
        )

    logger.warning(
        "Batch compensation completed with local request file preserved at %s",
        local_file_path,
    )


async def run_batch_download(client) -> BatchDownloadResult:
    """Check the oldest pending batch job and persist its results."""
    row = get_batch_with_given_status(status="pending")
    if not row:
        raise NoPendingBatchError("No pending batch jobs found")

    job_id = row["job_id"]
    batch_job = await retrieve_batch_job(job_id, client)

    output_file_id = getattr(batch_job, "output_file_id", None)
    error_file_id = getattr(batch_job, "error_file_id", None)

    if output_file_id:
        output_path = f"./data/processed/{job_id}.jsonl"
        await download_batch_file(output_file_id, client, output_path)
        update_batch_job_status(
            job_id, status="completed", file_path_write=output_path
        )
        return BatchDownloadResult(
            job_id=job_id,
            outcome="completed",
            output_path=output_path,
        )

    if error_file_id:
        error_path = f"./data/processed/errors/{job_id}_errors.jsonl"
        await download_batch_file(error_file_id, client, error_path)
        update_batch_job_status(job_id, status="failed")
        return BatchDownloadResult(
            job_id=job_id,
            outcome="failed",
            error_path=error_path,
            provider_status=str(batch_job.status),
        )

    return BatchDownloadResult(
        job_id=job_id,
        outcome="in_progress",
        provider_status=str(batch_job.status),
    )


def merge_bookmark_entries(bookmark_entries, processed_entries):
    """Attach resolved URLs back onto processed summaries by bookmark ID."""
    url_mapping = {
        entry.id: entry.url for entry in bookmark_entries
    }
    for processed in processed_entries:
        bookmark_id = processed.id.split("-")[1]
        if bookmark_id in url_mapping:
            processed.url = url_mapping[bookmark_id]
    return processed_entries


async def run_categorization(
    client,
    bookmarks_file: str = "bookmarks.md",
    max_entries: int | None = None,
) -> UpdateResult:
    """Merge parsed bookmarks with summaries and run the decision pipeline."""
    bookmark_entries, batch_hints = parse_bookmarks_file(bookmarks_file)
    processed_summaries = parse_processed_bookmarks()
    enriched = merge_bookmark_entries(bookmark_entries, processed_summaries)

    if max_entries is not None:
        enriched = enriched[:max_entries]

    final_decisions = await orchestrate_discussion(
        client, enriched, batch_hints
    )
    return UpdateResult(final_decisions=final_decisions)


def build_bookmark_graph(
    config: dict,
    cache_path: str = "./data/bookmark_graph.pkl",
) -> dict[str, int]:
    """Build the bookmark tree from configured files and persist it."""
    bookmark_config = config.get("bookmark")
    if not bookmark_config:
        raise ConfigError("config.yaml must define a 'bookmark' mapping")

    tree = BookmarkTree()
    inserted = {}
    for tree_path, file_path in extract_bookmark_files(bookmark_config).items():
        node = tree.insert_file(tree_path, file_path)
        if node is not None:
            inserted[node.name] = node.total_entries

    tree.save_tree(cache_path)
    return inserted


def generate_bookmark_graph(config: dict) -> dict[str, int]:
    """Compatibility wrapper used by callers without a preloaded config."""
    return build_bookmark_graph(config)
