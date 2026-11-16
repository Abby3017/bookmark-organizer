"""Self-check for Jev classification: fake HTTP and Langfuse client, no network.

Run with: python tests/test_jev_classifier.py
"""

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bookmark_agent.agents import jev_classifier as jev


CANDIDATES = {
    "ai#Libraries": {
        "path": "ai",
        "section": "Libraries",
        "entry_count": 1,
        "example_titles": ["PyTorch"],
    }
}
RESPONSE = {
    "model": "typesafe/jev-1.13",
    "answers": {
        "placement": {
            "choice": "ai#Libraries",
            "confidence": 0.9,
            "probabilities": {"ai#Libraries": 0.9},
        }
    },
    "usage": {"input_tokens": 128, "output_tokens": 0, "cost": 0.0000384},
}


class _FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return RESPONSE


class _FakeHTTPClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *args, **kwargs):
        return _FakeResponse()


def test_cost_is_reported_to_langfuse():
    entry = SimpleNamespace(
        id="summary-1", url="https://pytorch.org", title="PyTorch", summary=None
    )
    langfuse = MagicMock()
    jev.httpx.AsyncClient = _FakeHTTPClient
    jev.get_client = lambda: langfuse
    os.environ["OPENROUTER_PRJ_API_KEY"] = "test-key"

    # __wrapped__ skips the Langfuse observe wrapper; only the body is under test.
    result = asyncio.run(jev.classify_bookmark_with_jev.__wrapped__(entry, CANDIDATES))

    assert result.choice == "ai#Libraries"
    langfuse.update_current_generation.assert_called_once_with(
        model="typesafe/jev-1.13",
        usage_details={"input": 128, "output": 0},
        cost_details={"total": 0.0000384},
    )


if __name__ == "__main__":
    test_cost_is_reported_to_langfuse()
    print("all jev classifier self-checks passed")
