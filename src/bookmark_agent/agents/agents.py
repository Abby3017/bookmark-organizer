import json
from typing import Any, List

from pydantic import BaseModel, ConfigDict, Field

from utils.tree_helpers import tree_to_dict

class AgentProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    path: str
    section: str
    subsection_split: List[str] = Field(
        description="Two to four subsection names when the target section has 30 or more entries; otherwise an empty list.",
    )
    tags: List[str] = Field(
        description="Relevant tags for the bookmark."
    )
    reasoning: str

class AgentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposals: List[AgentProposal]
    # in future one request should have multiple bookmarks request
    # have to create another orchestration around it
    # as making sure it doesn't cause large prompt and responses
    # context limit based on model used
    # one bad bookmark entry will fail response of others
    # context sharing by all bookmarks


AGENT_ROLES = {
    "taxonomy": "Focus on structural fit: choose the most appropriate existing file and section in the bookmark tree.",
    "similarity": "Focus on semantic consistency: compare the bookmark with the most similar existing entries.",
    "critic": "Focus on invalid or weak choices: challenge assumptions and select the most defensible placement.",
}


def format_entry(entry: Any) -> str:
    """Format one processed bookmark as readable prompt input."""
    summary = entry.summary
    bullets = summary.bullets if summary else []
    tags = summary.tags if summary else []
    return "\n".join([
        f"ID: {entry.id}",
        f"URL: {entry.url}",
        f"Existing title: {getattr(entry, 'title', '') or '(not available)' }",
        f"Summary: {'; '.join(bullets)}",
        f"Tags: {', '.join(tags)}",
    ])


def build_chat_request(role: str, entry: Any, tree: Any, batch_hint: str | None = None) -> dict:
    if role not in AGENT_ROLES:
        raise ValueError(f"Unknown agent role: {role}")

    system_prompt = f"""You are the {role} agent in a bookmark classification system.
            {AGENT_ROLES[role]}

            Return exactly one proposal for the supplied bookmark. Use only paths and sections
            that exist in the tree. If the selected section has 30 or more entries, provide
            2-4 subsection names; otherwise return an empty subsection_split list.
        """
    user_prompt = f"Bookmark:\n{format_entry(entry)}\n\nBookmark tree:\n{json.dumps(tree_to_dict(tree), indent=2)}"
    if batch_hint:
        user_prompt += f"\n\nUser hint:\n{batch_hint}"

    return {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "agent_response",
                "schema": AgentProposal.model_json_schema(),
                "strict": True,
            },
        },
    }

# how can we send chat to last session of this instance
def build_round_two_chat_request(
    role: str,
    entry: Any,
    tree: Any,
    own_proposal: dict,
    peer_proposals: dict,
    batch_hint: str | None = None,
) -> dict:
    """Build a Round 2 request using the other agents' proposals as context."""
    if role not in AGENT_ROLES:
        raise ValueError(f"Unknown agent role: {role}")

    system_prompt = f"""You are the {role} agent in Round 2 of bookmark classification.
            {AGENT_ROLES[role]}

            Review your original proposal and the other agents' proposals. Select the single
            most defensible path and section. You may keep your original proposal or revise it.
            Return exactly one proposal. Do not return alternatives or mention this instruction
            in the reasoning.
    """
    user_prompt = (
        f"Bookmark:\n{format_entry(entry)}\n\n"
        f"Bookmark tree:\n{json.dumps(tree_to_dict(tree), indent=2)}\n\n"
        f"Your Round 1 proposal:\n{json.dumps(own_proposal, indent=2)}\n\n"
        f"Other agents' Round 1 proposals:\n{json.dumps(peer_proposals, indent=2)}"
    )
    if batch_hint:
        user_prompt += f"\n\nUser hint:\n{batch_hint}"

    request = build_chat_request(role, entry, tree, batch_hint)
    request["messages"] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return request


def build_coordinator_chat_request(
    entry: Any,
    tree: Any,
    round_one_discussion: dict,
    round_two_discussion: dict,
    batch_hint: str | None = None,
) -> dict:
    """Build a request for the coordinator's final placement decision."""
    system_prompt = """You are the coordinator of a bookmark classification discussion.

        Review the bookmark tree, the original bookmark, and the proposals from Round 1
        and Round 2. Select the single best final path and section. Prefer the Round 2
        decision when it is better supported, but resolve any remaining disagreement
        using the bookmark content and the tree structure.

        Return exactly one final proposal using the required schema. Do not return
        alternatives.

    """
    user_prompt = (
        f"Bookmark:\n{format_entry(entry)}\n\n"
        f"Bookmark tree:\n{json.dumps(tree_to_dict(tree), indent=2)}\n\n"
        f"Round 1 proposals:\n{json.dumps(round_one_discussion, indent=2)}\n\n"
        f"Round 2 proposals:\n{json.dumps(round_two_discussion, indent=2)}"
    )
    if batch_hint:
        user_prompt += f"\n\nUser hint:\n{batch_hint}"

    return {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "coordinator_proposal",
                "schema": AgentProposal.model_json_schema(),
                "strict": True,
            },
        },
    }


def parse_agent_response_content(content: str) -> AgentProposal:
    return AgentProposal.model_validate_json(content)


async def call_agent(client, role: str, entry: Any, tree: Any,
                     temperature: float, batch_hint: str | None = None) -> AgentProposal:
    request = build_chat_request(role, entry, tree, batch_hint)
    request["temperature"] = temperature
    response = await client.chat.completions.create(**request)
    content = (response.choices[0].message.content or "").strip()
    return parse_agent_response_content(content)


async def call_agent_round_two(
    client,
    role: str,
    entry: Any,
    tree: Any,
    own_proposal: dict,
    peer_proposals: dict,
    temperature: float,
    batch_hint: str | None = None,
) -> AgentProposal:
    """Call one agent for Round 2 and validate its revised proposal."""
    request = build_round_two_chat_request(
        role, entry, tree, own_proposal, peer_proposals, batch_hint
    )
    request["temperature"] = temperature
    response = await client.chat.completions.create(**request)
    content = (response.choices[0].message.content or "").strip()
    return parse_agent_response_content(content)


async def call_coordinator(
    client,
    entry: Any,
    tree: Any,
    round_one_discussion: dict,
    round_two_discussion: dict,
    batch_hint: str | None = None,
) -> AgentProposal:
    """Return the coordinator's final proposal for one bookmark."""
    request = build_coordinator_chat_request(
        entry,
        tree,
        round_one_discussion,
        round_two_discussion,
        batch_hint,
    )
    response = await client.chat.completions.create(**request)
    content = (response.choices[0].message.content or "").strip()
    return parse_agent_response_content(content)
