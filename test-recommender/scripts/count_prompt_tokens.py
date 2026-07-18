"""Measure exact token counts of the recommend.py system prompts.

Uses Anthropic's count_tokens endpoint to get the authoritative number for the
model we run in production. Prints a table with a verdict on whether each
prompt exceeds the 1024-token minimum required for prompt caching.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Import the actual prompts from recommend.py without running the pipeline
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from recommend import (  # noqa: E402
    LLM_MODEL_RERANK,
    LLM_MODEL_SYNTHESIZE,
    SYSTEM_PROMPT_RERANK,
    SYSTEM_PROMPT_SYNTHESIZE,
)

import anthropic  # noqa: E402


CACHE_MIN_TOKENS = 1024

client = anthropic.Anthropic()


def count(model: str, prompt: str) -> int:
    resp = client.messages.count_tokens(
        model=model,
        system=[{"type": "text", "text": prompt}],
        messages=[{"role": "user", "content": "x"}],   # minimal placeholder
    )
    total = resp.input_tokens
    # Subtract 1 token roughly for the "x" user message; enough for verdict purposes
    system_only = total - 1
    return system_only


def main() -> None:
    print(f"Cache minimum: {CACHE_MIN_TOKENS} tokens")
    print()
    print(f"{'Prompt':<28}{'Model':<20}{'Tokens':>10}{'Cacheable?':>18}")
    print("-" * 76)

    # Render placeholders with realistic values so the count reflects what
    # actually gets sent to the API in production.
    rerank_rendered = SYSTEM_PROMPT_RERANK.format(budget_lo=40, budget_hi=70)

    for name, prompt, model in [
        ("SYSTEM_PROMPT_RERANK", rerank_rendered, LLM_MODEL_RERANK),
        ("SYSTEM_PROMPT_SYNTHESIZE", SYSTEM_PROMPT_SYNTHESIZE, LLM_MODEL_SYNTHESIZE),
    ]:
        n = count(model, prompt)
        verdict = "yes" if n >= CACHE_MIN_TOKENS else f"NO (short by {CACHE_MIN_TOKENS - n})"
        print(f"{name:<28}{model:<20}{n:>10}{verdict:>18}")


if __name__ == "__main__":
    main()
