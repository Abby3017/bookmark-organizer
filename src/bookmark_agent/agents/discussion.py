"""First-round real-time discussion between the bookmark agents."""

import asyncio
import os
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict, List
import logging
import yaml

from bookmark_agent.agents.agents import (
    AgentProposal,
    call_agent,
    call_agent_round_two,
    call_coordinator,
)
from bookmark_agent.domain.bookmark_tree import load_tree
from bookmark_agent.agents.jev_classifier import (
    CLASSIFICATION_THRESHOLD,
    classify_bookmark_with_jev,
    jev_to_proposal,
)
from models.article_summary import ProcessedArticleSummary
from utils.tree_helpers import candidate_sections


AGENT_ROLES = ("taxonomy", "similarity", "critic")
DEFAULT_TEMPERATURES = {"taxonomy": 0.2, "similarity": 0.6, "critic": 0.8}


def _load_config(config_path: str = "config.yaml") -> dict:
    with open(config_path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def _response_to_dict(response: AgentProposal) -> dict:
    return response.model_dump(mode="json")


async def _discuss_one_entry(client, entry, tree, batch_hint, temperatures):
    tasks = [
        call_agent(client, role, entry, tree, temperatures[role], batch_hint)
        for role in AGENT_ROLES
    ]
    responses = await asyncio.gather(*tasks)
    return {role: _response_to_dict(response) for role, response in zip(AGENT_ROLES, responses)}

def parse_agent_discussion(results):
    agreed_bookmark_position: list[dict] = []
    disagreed_bookmark_entries: list[str] = []
    for discussion in results:
        bookmark_id = None
        path_section_list = []
        tags = None
        for agent in AGENT_ROLES:
            agent_discussion = discussion[agent]
            if not bookmark_id:
                bookmark_id = agent_discussion['id']
            if not tags:
                tags = agent_discussion['tags']
            path_section = agent_discussion['path'] + "#" + agent_discussion['section']
            path_section_list.append(path_section)
        result = all(x == path_section_list[0] for x in path_section_list)
        if result:
            path, section = path_section_list[0].split("#", maxsplit=1)
            agreed_bookmark_position.append({"id": bookmark_id, "path": path,
                                             "section": section, "tags": tags})
        else:
            disagreed_bookmark_entries.append(bookmark_id)
    return agreed_bookmark_position, disagreed_bookmark_entries

def _peer_proposals(discussion: dict, current_role: str) -> dict:
    """Return all Round 1 proposals except the current agent's proposal."""
    return {
        role: proposal
        for role, proposal in discussion.items()
        if role != current_role
    }

async def _discuss_round_two(
    client,
    entry,
    tree,
    round_one_discussion,
    batch_hint: str | None,
    temperatures: dict[str, float],
) -> dict:
    """Ask each agent to revise its proposal using Round 1 peer proposals."""
    tasks = [
        call_agent_round_two(
            client=client,
            role=role,
            entry=entry,
            tree=tree,
            own_proposal=round_one_discussion[role],
            peer_proposals=_peer_proposals(round_one_discussion, role),
            temperature=temperatures[role],
            batch_hint=batch_hint,
        )
        for role in AGENT_ROLES
    ]
    responses = await asyncio.gather(*tasks)
    return {
        role: _response_to_dict(response)
        for role, response in zip(AGENT_ROLES, responses)
    }

def _save_json(output_folder, responses, round_number):
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_file = Path(output_folder) / f"round_response_{round_number}_{timestamp}.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(responses, indent=2), encoding="utf-8")

async def _run_coordinator(
        client,
        entry,
        tree,
        round_one_discussion,
        round_two_discussion,
        batch_hint: str | None
):
    """
    future usefulness of this fn:
    Coordinator retry handling
    Logging
    Error handling
    Result normalization
    Calling the coordinator for multiple entries
    """
    response = await call_coordinator(
        client=client,
        entry=entry,
        tree=tree,
        round_one_discussion=round_one_discussion,
        round_two_discussion=round_two_discussion,
        batch_hint=batch_hint,
    )
    return _response_to_dict(response)

async def orchestrate_discussion(
    client,
    entries: List[ProcessedArticleSummary],
    batch_hint: str | None = None,
    config_path: str = "config.yaml",
) -> List[Dict[str, Any]]:
    """Run Round 1, Round 2 when needed, then coordinator arbitration."""
    config = _load_config(config_path)
    tree_path = config.get("stored_bookmark_graph_path")
    if not tree_path:
        raise ValueError("config.yaml must define stored_bookmark_graph_path")

    temperatures = DEFAULT_TEMPERATURES.copy()
    temperatures.update(dict(zip(AGENT_ROLES, config.get("temperatures", []))))
    tree = load_tree(tree_path)
    candidates = candidate_sections(tree)

    # Use Jev to classify every bookmark against the real path/section labels.
    # Only uncertain classifications enter the more expensive actor-critic flow.
    jev_results = await asyncio.gather(*(
        classify_bookmark_with_jev(entry, candidates)
        for entry in entries
    ))
    jev_by_id = {
        result.bookmark_id: result
        for result in jev_results
    }
    accepted_entries = [
        jev_to_proposal(jev_by_id[str(entry.id)], entry)
        for entry in entries
        if jev_by_id[str(entry.id)].confidence >= CLASSIFICATION_THRESHOLD
    ]
    fallback_entries = [
        entry
        for entry in entries
        if jev_by_id[str(entry.id)].confidence < CLASSIFICATION_THRESHOLD
    ]

    if not fallback_entries:
        logging.debug("Jev accepted all bookmark classifications")
        return accepted_entries

    # Round 1: ask all three agents for a proposal.
    round_one_results = await asyncio.gather(*(
        _discuss_one_entry(client, entry, tree, batch_hint, temperatures)
        for entry in fallback_entries
    ))

    entries_by_id = {str(entry.id): entry for entry in fallback_entries}
    round_one_by_id = {
        str(entry.id): result
        for entry, result in zip(fallback_entries, round_one_results)
    }
    output_folder = config.get("agent_discussion_path", os.getcwd())
    _save_json(output_folder, round_one_by_id, "1")

    agreed_round_one, disputed_ids = parse_agent_discussion(round_one_results)
    final_entries = accepted_entries + agreed_round_one

    # No disagreement means no Round 2 or coordinator calls are needed.
    if not disputed_ids:
        logging.debug(f"Round1, no disagreement, Len of bookmark processed {len(final_entries)}")
        return final_entries

    # Round 2: only disputed bookmarks see the other agents' proposals.
    round_two_results_list = await asyncio.gather(*(
        _discuss_round_two(
            client=client,
            entry=entries_by_id[bookmark_id],
            tree=tree,
            round_one_discussion=round_one_by_id[bookmark_id],
            batch_hint=batch_hint,
            temperatures=temperatures,
        )
        for bookmark_id in disputed_ids
    ))
    round_two_by_id = {
        bookmark_id: result
        for bookmark_id, result in zip(disputed_ids, round_two_results_list)
    }
    _save_json(output_folder, round_two_by_id, "2")

    agreed_round_two, still_disputed_ids = parse_agent_discussion(
        round_two_results_list
    )
    final_entries.extend(agreed_round_two)

    # Everything still unresolved goes to the coordinator.
    if not still_disputed_ids:
        logging.debug(f"Round1, number of disagreement {len(disputed_ids)}")
        logging.debug(f"Round2, no disagreement, Len of bookmark processed {len(final_entries)}")
        return final_entries

    coordinator_results = await asyncio.gather(*(
        _run_coordinator(
            client=client,
            entry=entries_by_id[bookmark_id],
            tree=tree,
            round_one_discussion=round_one_by_id[bookmark_id],
            round_two_discussion=round_two_by_id[bookmark_id],
            batch_hint=batch_hint,
        )
        for bookmark_id in still_disputed_ids
    ))
    coordinator_by_id = {
        bookmark_id: result
        for bookmark_id, result in zip(still_disputed_ids, coordinator_results)
    }
    _save_json(output_folder, coordinator_by_id, "coordinator")
    for proposal in coordinator_results:
        final_entries.append({
            "id": proposal["id"],
            "path": proposal["path"],
            "section": proposal["section"],
            "tags": proposal["tags"],
        })
    logging.debug(f"Round2, number of disagreement {len(still_disputed_ids)}")
    logging.debug(f"Round2, no disagreement, Len of bookmark processed {len(final_entries)}")

    return final_entries