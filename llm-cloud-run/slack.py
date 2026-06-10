#!/usr/bin/env python3
"""Build Slack Block Kit payloads for LLM analysis output.

Usage:
    python slack.py --output "LLM analysis text here" --run-url "https://..." --dest /tmp/slack-payload.json

    # Read output from a file instead
    python slack.py --output-file /tmp/llm_output.txt --run-url "https://..." --dest /tmp/slack-payload.json

    # Use a custom template
    python slack.py --output "..." --template path/to/template.json --run-url "https://..." --dest /tmp/slack-payload.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_TEMPLATE = Path(__file__).parent / "slack-product-health-pulse.json"


def build_payload(
    output: str,
    run_url: str | None = None,
    template_path: Path | None = None,
) -> dict:
    """Build a Slack Block Kit payload from LLM output.

    If a template is provided, it's used as the base structure with
    ${LLM_OUTPUT} and ${RUN_URL} placeholders replaced. Otherwise,
    a default Block Kit layout is constructed.
    """
    if template_path and template_path.exists():
        raw = template_path.read_text()
        raw = raw.replace("${LLM_OUTPUT}", _escape_slack_json(output))
        raw = raw.replace("${RUN_URL}", run_url or "")
        return json.loads(raw)

    source_parts = [":chart_with_upwards_trend: Source: Sentry crash-free rates"]
    if run_url:
        source_parts.append(f"<{run_url}|View run>")
    source_parts.append("React :+1: useful :-1: not useful :speech_balloon: what's missing")
    context_text = " | ".join(source_parts)

    return {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": ":brain: Product health pulse",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": output,
                },
            },
            {"type": "divider"},
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": context_text,
                    }
                ],
            },
        ]
    }


def _escape_slack_json(text: str) -> str:
    """Escape text for safe embedding inside a JSON string value."""
    return json.dumps(text)[1:-1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Slack payload from LLM output")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--output", help="LLM output text")
    group.add_argument("--output-file", type=Path, help="Path to file containing LLM output")
    parser.add_argument("--run-url", help="GitHub Actions run URL")
    parser.add_argument("--template", type=Path, default=None, help="Path to Slack template JSON")
    parser.add_argument("--dest", type=Path, required=True, help="Output path for the payload JSON")
    args = parser.parse_args()

    if args.output_file:
        if not args.output_file.exists():
            print(f"Error: output file not found: {args.output_file}", file=sys.stderr)
            sys.exit(1)
        output = args.output_file.read_text().strip()
    else:
        output = args.output

    payload = build_payload(
        output=output,
        run_url=args.run_url,
        template_path=args.template,
    )

    args.dest.parent.mkdir(parents=True, exist_ok=True)
    args.dest.write_text(json.dumps(payload, ensure_ascii=False))
    print(f"Slack payload written to {args.dest}")


if __name__ == "__main__":
    main()
