"""Tests for agent/cost.py — token tracking and TrackedClient wiring.

USD estimation was removed: tokens are ground truth (exact from the API);
USD would require a manually maintained pricing table that drifts silently.
See agent/cost.py header for the full rationale.
"""

from unittest.mock import MagicMock, patch

from agent.cost import CostTracker, TrackedClient


# ── record() ───────────────────────────────────────────────────────────────────

def test_record_accumulates_tokens_by_call():
    tracker = CostTracker()
    tracker.record("claude-haiku-4-5", input_tokens=100, output_tokens=50)
    tracker.record("claude-sonnet-4-6", input_tokens=200, output_tokens=80)

    assert tracker.total_input_tokens  == 300
    assert tracker.total_output_tokens == 130
    assert tracker.total_tokens        == 430
    assert len(tracker._calls) == 2


def test_record_tracks_cache_tokens_separately():
    """Cache read tokens come from usage.cache_read_input_tokens; cache write
    from usage.cache_creation_input_tokens. Both are billed at different rates
    upstream — we surface them separately so users can reason about them."""
    tracker = CostTracker()
    tracker.record("claude-sonnet-4-6",
                   input_tokens=100, output_tokens=50,
                   cache_read_tokens=1000, cache_write_tokens=200)
    assert tracker.total_cache_read_tokens  == 1000
    assert tracker.total_cache_write_tokens == 200
    # total_tokens folds them all in — used by the budget cap.
    assert tracker.total_tokens == 100 + 50 + 1000 + 200


def test_record_stores_purpose_tag():
    tracker = CostTracker()
    tracker.record("claude-haiku-4-5", 100, 50, purpose="reasoning")
    assert tracker._calls[0]["purpose"] == "reasoning"


# ── summary() ──────────────────────────────────────────────────────────────────

def test_summary_by_model_groups_calls_correctly():
    tracker = CostTracker()
    tracker.record("claude-haiku-4-5",  100, 50)
    tracker.record("claude-haiku-4-5",  200, 100)
    tracker.record("claude-sonnet-4-6", 500, 200)

    s = tracker.summary()
    assert s["by_model"]["claude-haiku-4-5"]["calls"]         == 2
    assert s["by_model"]["claude-haiku-4-5"]["input_tokens"]  == 300
    assert s["by_model"]["claude-haiku-4-5"]["output_tokens"] == 150
    assert s["by_model"]["claude-sonnet-4-6"]["calls"]        == 1


def test_summary_by_purpose_groups_calls_correctly():
    tracker = CostTracker()
    tracker.record("claude-haiku-4-5", 100, 50, purpose="reasoning")
    tracker.record("claude-haiku-4-5", 200, 100, purpose="reasoning")
    tracker.record("claude-haiku-4-5", 300, 150, purpose="memory-extraction")

    s = tracker.summary()
    assert s["by_purpose"]["reasoning"]["calls"]        == 2
    assert s["by_purpose"]["reasoning"]["input_tokens"] == 300
    assert s["by_purpose"]["memory-extraction"]["calls"] == 1


def test_summary_missing_purpose_becomes_unspecified():
    tracker = CostTracker()
    tracker.record("claude-haiku-4-5", 100, 50)   # no purpose
    s = tracker.summary()
    assert "unspecified" in s["by_purpose"]
    assert s["by_purpose"]["unspecified"]["calls"] == 1


def test_summary_carries_totals_including_cache():
    tracker = CostTracker()
    tracker.record("claude-sonnet-4-6", 100, 50,
                   cache_read_tokens=500, cache_write_tokens=100,
                   purpose="reasoning")

    s = tracker.summary()
    assert s["total_calls"]              == 1
    assert s["total_input_tokens"]       == 100
    assert s["total_output_tokens"]      == 50
    assert s["total_cache_read_tokens"]  == 500
    assert s["total_cache_write_tokens"] == 100
    assert s["total_tokens"]             == 750


def test_summary_never_reports_usd_cost():
    """Regression: the old summary() included total_cost_usd. That's gone —
    the session JSON should only contain token metrics."""
    tracker = CostTracker()
    tracker.record("claude-haiku-4-5", 100, 50)
    s = tracker.summary()

    # No cost fields should exist anywhere in the summary
    forbidden = ("cost", "usd", "price", "dollar")
    def scan(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert not any(t in k.lower() for t in forbidden), (
                    f"summary() leaked a cost-like key: {k!r}"
                )
                scan(v)
        elif isinstance(obj, list):
            for item in obj:
                scan(item)
    scan(s)


# ── TrackedClient ──────────────────────────────────────────────────────────────

@patch("agent.cost.anthropic.Anthropic")
def test_tracked_client_forwards_call_and_records_usage(mock_anthropic_class):
    """TrackedClient must call the SDK and record the response's usage on the tracker."""
    mock_response = MagicMock()
    mock_response.usage.input_tokens                = 100
    mock_response.usage.output_tokens               = 50
    mock_response.usage.cache_read_input_tokens     = 0
    mock_response.usage.cache_creation_input_tokens = 0

    mock_client_instance = MagicMock()
    mock_client_instance.messages.create.return_value = mock_response
    mock_anthropic_class.return_value = mock_client_instance

    tracker = CostTracker()
    client  = TrackedClient(tracker)

    response = client.messages_create(
        "test-purpose",
        model="claude-haiku-4-5",
        max_tokens=100,
        messages=[{"role": "user", "content": "hi"}],
    )

    mock_client_instance.messages.create.assert_called_once_with(
        model="claude-haiku-4-5",
        max_tokens=100,
        messages=[{"role": "user", "content": "hi"}],
    )
    assert tracker.total_input_tokens         == 100
    assert tracker.total_output_tokens        == 50
    assert tracker._calls[0]["purpose"]       == "test-purpose"
    assert response is mock_response


@patch("agent.cost.anthropic.Anthropic")
def test_tracked_client_normalizes_none_cache_fields(mock_anthropic_class):
    """When prompt caching isn't in use the API returns None for the cache
    counters. TrackedClient must coerce those to 0 before recording."""
    mock_response = MagicMock()
    mock_response.usage.input_tokens                = 10
    mock_response.usage.output_tokens               = 5
    mock_response.usage.cache_read_input_tokens     = None   # ← the case that used to crash
    mock_response.usage.cache_creation_input_tokens = None

    mock_client_instance = MagicMock()
    mock_client_instance.messages.create.return_value = mock_response
    mock_anthropic_class.return_value = mock_client_instance

    tracker = CostTracker()
    client  = TrackedClient(tracker)

    client.messages_create("x", model="claude-haiku-4-5",
                           max_tokens=10, messages=[{"role":"user","content":"hi"}])
    assert tracker.total_cache_read_tokens  == 0
    assert tracker.total_cache_write_tokens == 0
