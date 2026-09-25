"""Jev classification for selecting a bookmark path and section."""

from dataclasses import asdict, dataclass
import json
import os
from typing import Any

import httpx

from bookmark_agent.agents.agents import AgentProposal, format_entry
from utils.tree_helpers import tree_to_dict


DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
JEV_MODEL = "typesafe/jev-1.13"
CLASSIFICATION_THRESHOLD = 0.80


@dataclass(frozen=True)
class JevClassification:
    """Jev's selected candidate and confidence for one bookmark."""

    bookmark_id: str
    choice: str
    confidence: float
    probabilities: dict[str, float]
    usage: dict[str, Any]

    def to_dict(self) -> dict:
        return asdict(self)


def build_jev_request(entry: Any, candidates: Any) -> dict[str, Any]:
    criteria = {
        label: (
            f"Place the bookmark in path '{details['path']}', section "
            f"'{details['section']}'. This section currently has "
            f"{details['entry_count']} entries. Example titles: "
            f"{details['example_titles']}"
        )
        for label, details in candidates.items()
    }
    state = {
        "bookmark": format_entry(entry),
        "candidate_sections": candidates,
    }
    questions = {
        "placement": {
            "type": "choice",
            "instructions": "Which single candidate path and section best fits the bookmark?",
            "criteria": criteria,
        }
    }
    return {"model": JEV_MODEL, "state": state, "questions": questions}


async def classify_bookmark_with_jev(
    entry: Any,
    candidates: Any,
) -> JevClassification:
    """Classify one bookmark through OpenRouter's Jev Decisions API."""
    api_key = os.getenv("OPENROUTER_PRJ_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_PRJ_API_KEY is required for Jev classification")

    payload = build_jev_request(entry, candidates)
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            DECISIONS_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    answer = data.get("answers", {}).get("placement", {})
    choice = answer.get("choice")
    if choice not in candidates:
        raise ValueError(f"Jev returned an unknown candidate section: {choice!r}")

    return JevClassification(
        bookmark_id=str(entry.id),
        choice=choice,
        confidence=float(answer.get("confidence") or 0.0),
        probabilities=answer.get("probabilities") or {},
        usage=data.get("usage") or {},
    )


def jev_to_proposal(classification: JevClassification, entry: Any) -> dict:
    """Convert an accepted Jev choice to the project's proposal shape."""
    path, section = classification.choice.split("#", maxsplit=1)
    summary = entry.summary
    return AgentProposal(
        id=classification.bookmark_id,
        path=path,
        section=section,
        subsection_split=[],
        tags=list(summary.tags) if summary else [],
        reasoning=(
            f"Jev selected this candidate with confidence "
            f"{classification.confidence:.2f}."
        ),
    ).model_dump(mode="json")
