"""Self-check for the harness loop: fake client, no network, no API key.

Run with: python tests/test_harness.py
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# sqlite_store runs load_settings() at import, so a config.yaml must exist in cwd.
_TMP = tempfile.mkdtemp()
Path(_TMP, "config.yaml").write_text("db_path: test.db\n", encoding="utf-8")
os.chdir(_TMP)

from bookmark_agent.domain.bookmark_tree import (
    BookmarkEntry,
    BookmarkNode,
    BookmarkTree,
    SectionNode,
)
from bookmark_agent.harness import TOOLS, run_agent


def _fake_client(script, seen):
    """Client whose responses follow `script`; records every messages list."""
    async def create(**kwargs):
        seen.append(list(kwargs["messages"]))
        return SimpleNamespace(choices=[SimpleNamespace(message=next(script))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def _tool_call_message(name, arguments="{}"):
    call = SimpleNamespace(id="call_1", function=SimpleNamespace(name=name, arguments=arguments))
    return SimpleNamespace(content=None, tool_calls=[call])


def _final_message(text):
    return SimpleNamespace(content=text, tool_calls=None)


def _make_tree(path):
    tree = BookmarkTree()
    node = BookmarkNode(name="ai", path="ai")
    section = SectionNode(name="Libraries")
    section.entries.append(BookmarkEntry(title="PyTorch", url="https://pytorch.org"))
    node.sections["Libraries"] = section
    tree.root.children["ai"] = node
    tree.save_tree(path)


def _tool_messages(messages):
    return [m for m in messages if isinstance(m, dict) and m.get("role") == "tool"]


def test_tool_names_unique():
    names = [t["function"]["name"] for t in TOOLS]
    assert len(names) == len(set(names)), f"duplicate tool names: {names}"


def test_agent_explores_tree_then_answers():
    with tempfile.TemporaryDirectory() as tmp:
        tree_path = str(Path(tmp) / "tree.pkl")
        _make_tree(tree_path)
        seen = []
        client = _fake_client(iter([
            _tool_call_message("list_bookmark_sections"),
            _final_message("Found the tree."),
        ]), seen)
        answer = asyncio.run(run_agent("What sections exist?", client,
                                       {"stored_bookmark_graph_path": tree_path}))
        assert answer == "Found the tree."
        tool_msgs = _tool_messages(seen[-1])
        assert tool_msgs and "ai#Libraries" in tool_msgs[0]["content"], tool_msgs


def test_tool_error_is_fed_back_not_raised():
    seen = []
    client = _fake_client(iter([
        _tool_call_message("list_bookmark_sections"),
        _final_message("No tree yet."),
    ]), seen)
    # Empty config: tree path missing -> tool must return {"error": ...}, not raise.
    answer = asyncio.run(run_agent("List sections", client, {}))
    assert answer == "No tree yet."
    tool_msgs = _tool_messages(seen[-1])
    assert tool_msgs and "error" in tool_msgs[0]["content"], tool_msgs


if __name__ == "__main__":
    test_tool_names_unique()
    test_agent_explores_tree_then_answers()
    test_tool_error_is_fed_back_not_raised()
    print("all harness self-checks passed")
