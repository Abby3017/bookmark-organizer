from dataclasses import dataclass
from typing import Any, Sequence
import json
from utils import batch_request

from models.article_summary import ArticleSummary


@dataclass(frozen=True)
class BatchSubmission:
    """Remote resources created while submitting a batch."""

    batch_job: Any
    input_file_id: str
    local_file_path: str

TITLE_INSTRUCTIONS = """Create a concise, descriptive Markdown link title for the webpage.
Use the page's actual subject rather than the domain name or URL.
Prefer 3-10 words in title case or natural sentence case.
Do not include Markdown syntax, the URL, emojis, clickbait, or phrases such as
'Read more'. Preserve important proper nouns, technologies, and version numbers.
If an existing title is provided, improve it only when it is missing, generic,
or clearly inaccurate.
"""

def _build_summary_prompt(trimmed_text: str, url: str) -> str:
    return f"""
        Analyze the article and return a structured response.

            Requirements:
            - Return 1 to 3 concise bullet points.
            - Each bullet must contain at most one sentence.
            - Return exactly 5 relevant tags.
            - If the article is empty or lacks useful information, infer relevant
            information from the URL or well-known context.
            - Do not include any fields other than `bullets` and `tags`.
            - Article URL: {url}

            {TITLE_INSTRUCTIONS}

        Article content:
        {trimmed_text}
    """

def create_batch_requests(article_texts: Sequence[tuple[str, str, str]], path: str):
    requests = []
    for _, (id, url, text) in enumerate(article_texts):
        if not text:
            continue
        requests.append(
            {
                "custom_id": f"summary-{id}",
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": "gpt-4o-mini",
                    "messages": [ {
                        "role": "system",
                        "content": (
                            "You summarize articles and return only valid JSON "
                            "matching the provided schema."
                        ),
                    },
                    {
                        "role": "user",
                        "content": _build_summary_prompt(text, url),
                    },],
                    "response_format":{
                    "type": "json_schema",
                    "json_schema": {
                        "name": "article_summary",
                        "strict": True,
                        "schema": ArticleSummary.model_json_schema(),
                    },
                    },
                    "max_tokens": 400,
                    "temperature": 0.3,
                },
            }
        )

    with open(path, 'w') as f:
        for request in requests:
            f.write(json.dumps(request) + '\n')
        # json.dump(requests, f, indent=2)


async def create_and_upload_bookmark_summaries_batch(
    article_texts: Sequence[tuple[str, str, str]],
    client,
    path: str,
):
    create_batch_requests(article_texts, path)
    batch_file = await batch_request.upload_batch_file(client, path)
    try:
        batch_job = await batch_request.create_batch_job(batch_file.id, client)
    except Exception:
        # The file exists remotely, but no batch job was created.
        try:
            await client.files.delete(batch_file.id)
        except Exception:
            # Preserve the original exception. The workflow logs cleanup failure.
            pass
        raise

    return BatchSubmission(
        batch_job=batch_job,
        input_file_id=batch_file.id,
        local_file_path=path,
    )