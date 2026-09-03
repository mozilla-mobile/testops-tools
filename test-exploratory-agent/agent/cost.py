"""
agent/cost.py

Tracks Anthropic API token usage across a session.

Only tokens are tracked — no USD. Tokens are ground truth (exact, from
the API response); USD would require a manually maintained pricing table
that drifts silently as Anthropic changes rates. For authoritative billing
figures, use the Anthropic console: https://console.anthropic.com/settings/usage

What this module gives you that the console can't:
  - per-session token breakdown
  - per-model breakdown within a session
  - per-purpose breakdown (reasoning vs memory-extraction, etc.)
  - cache read/write tokens surfaced separately
"""

import anthropic


_MODEL_SHORT = {
    "claude-haiku-4-5":  "haiku",
    "claude-sonnet-4-6": "sonnet",
    "claude-opus-4-5":   "opus",
}


# ── Tracker ────────────────────────────────────────────────────────────────────

class CostTracker:
    """Accumulates Anthropic token usage across a session.

    Kept the name `CostTracker` on purpose to avoid a churn cascade through
    the rest of the codebase — semantically it's a UsageTracker now.
    """

    def __init__(self):
        self._calls:                    list[dict] = []
        self.total_input_tokens:        int = 0
        self.total_output_tokens:       int = 0
        self.total_cache_read_tokens:   int = 0
        self.total_cache_write_tokens:  int = 0

    @property
    def total_tokens(self) -> int:
        """All tokens counted in one number — the budget cap uses this."""
        return (self.total_input_tokens + self.total_output_tokens
                + self.total_cache_read_tokens + self.total_cache_write_tokens)

    def record(self,
               model:              str,
               input_tokens:       int,
               output_tokens:      int,
               cache_read_tokens:  int = 0,
               cache_write_tokens: int = 0,
               purpose:            str = ""):
        """Record one API call. `purpose` is a short tag (e.g. 'reasoning',
        'memory-extraction') used for the by-purpose breakdown in summary()."""
        self._calls.append({
            "model":              model,
            "purpose":            purpose,
            "input_tokens":       input_tokens,
            "output_tokens":      output_tokens,
            "cache_read_tokens":  cache_read_tokens,
            "cache_write_tokens": cache_write_tokens,
        })
        self.total_input_tokens       += input_tokens
        self.total_output_tokens      += output_tokens
        self.total_cache_read_tokens  += cache_read_tokens
        self.total_cache_write_tokens += cache_write_tokens

    def log_call(self, model: str, input_tokens: int, output_tokens: int, purpose: str = ""):
        """Print a one-line usage summary for the current call to stdout."""
        short = _MODEL_SHORT.get(model, model)
        tag   = f" [{purpose}]" if purpose else ""
        print(f"[usage] {short}{tag}: {input_tokens:,} in / {output_tokens:,} out "
              f"| session total: {self.total_tokens:,} tokens")

    def summary(self) -> dict:
        """Returns a dict suitable for inclusion in the session JSON.
        Breaks down tokens by model AND by purpose."""

        def _empty_bucket() -> dict:
            return {
                "calls":              0,
                "input_tokens":       0,
                "output_tokens":      0,
                "cache_read_tokens":  0,
                "cache_write_tokens": 0,
            }

        by_model:   dict[str, dict] = {}
        by_purpose: dict[str, dict] = {}
        for call in self._calls:
            m = call["model"]
            b = by_model.setdefault(m, _empty_bucket())
            b["calls"]              += 1
            b["input_tokens"]       += call["input_tokens"]
            b["output_tokens"]      += call["output_tokens"]
            b["cache_read_tokens"]  += call["cache_read_tokens"]
            b["cache_write_tokens"] += call["cache_write_tokens"]

            p = call.get("purpose") or "unspecified"
            b = by_purpose.setdefault(p, _empty_bucket())
            b["calls"]              += 1
            b["input_tokens"]       += call["input_tokens"]
            b["output_tokens"]      += call["output_tokens"]
            b["cache_read_tokens"]  += call["cache_read_tokens"]
            b["cache_write_tokens"] += call["cache_write_tokens"]

        return {
            "total_calls":               len(self._calls),
            "total_input_tokens":        self.total_input_tokens,
            "total_output_tokens":       self.total_output_tokens,
            "total_cache_read_tokens":   self.total_cache_read_tokens,
            "total_cache_write_tokens":  self.total_cache_write_tokens,
            "total_tokens":              self.total_tokens,
            "by_model":                  by_model,
            "by_purpose":                by_purpose,
        }

    def print_summary(self):
        """Print a formatted token breakdown to stdout."""
        s = self.summary()
        print(f"\n{'─'*50}")
        print(f"USAGE SUMMARY (see Anthropic console for authoritative $ cost)")
        print(f"  API calls:            {s['total_calls']}")
        print(f"  Input tokens:         {s['total_input_tokens']:,}")
        print(f"  Output tokens:        {s['total_output_tokens']:,}")
        if s["total_cache_read_tokens"] or s["total_cache_write_tokens"]:
            print(f"  Cache read tokens:    {s['total_cache_read_tokens']:,}")
            print(f"  Cache write tokens:   {s['total_cache_write_tokens']:,}")
        print(f"  Total tokens:         {s['total_tokens']:,}")
        if s["by_model"]:
            print(f"  By model:")
            for model, data in s["by_model"].items():
                short = _MODEL_SHORT.get(model, model)
                print(f"    {short:<8} {data['calls']:>3} calls  "
                      f"{data['input_tokens']:>8,} in  {data['output_tokens']:>6,} out")
        if s["by_purpose"]:
            print(f"  By purpose:")
            for purpose, data in s["by_purpose"].items():
                print(f"    {purpose:<18} {data['calls']:>3} calls  "
                      f"{data['input_tokens']:>8,} in  {data['output_tokens']:>6,} out")
        print(f"{'─'*50}")


# ── Tracked client ─────────────────────────────────────────────────────────────

class TrackedClient:
    """Wraps anthropic.Anthropic so every call passes through usage tracking.

    Every module that needs the LLM receives an instance of TrackedClient
    instead of a raw anthropic.Anthropic — this makes it impossible to make
    an untracked call by design.

    Usage:
        tracker = CostTracker()
        client  = TrackedClient(tracker)
        response = client.messages_create("reasoning", model=..., max_tokens=..., messages=[...])
    """

    def __init__(self, tracker: "CostTracker", timeout: float = 30.0):
        self._client  = anthropic.Anthropic(timeout=timeout)
        self._tracker = tracker

    def messages_create(self, purpose: str, **kwargs):
        """Forwards to anthropic.messages.create and records usage on the tracker.
        `purpose` is a short tag (e.g. 'reasoning', 'memory-extraction') used
        for the by-purpose breakdown in the usage summary."""
        response = self._client.messages.create(**kwargs)
        u = response.usage
        # cache_*_input_tokens can be None when caching isn't in use — normalize.
        cache_read  = getattr(u, "cache_read_input_tokens",     None) or 0
        cache_write = getattr(u, "cache_creation_input_tokens", None) or 0
        self._tracker.record(
            kwargs["model"],
            input_tokens       = u.input_tokens,
            output_tokens      = u.output_tokens,
            cache_read_tokens  = cache_read,
            cache_write_tokens = cache_write,
            purpose            = purpose,
        )
        self._tracker.log_call(kwargs["model"], u.input_tokens, u.output_tokens, purpose=purpose)
        return response
