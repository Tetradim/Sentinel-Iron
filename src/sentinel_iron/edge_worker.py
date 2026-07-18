from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from sentinel_iron.edge_strategy import EdgeStrategyClient, load_proposal


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sentinel-iron-edge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    propose = subparsers.add_parser("propose", help="Submit one futures strategy proposal to Edge.")
    propose.add_argument("proposal_file")
    propose.add_argument("--output")

    cards = subparsers.add_parser("cards", help="Read Edge trade cards assigned to Iron.")
    cards.add_argument("--include-terminal", action="store_true")

    feedback = subparsers.add_parser("feedback", help="Send execution or position feedback to Edge.")
    feedback.add_argument("feedback_file")

    args = parser.parse_args(list(argv) if argv is not None else None)
    client = EdgeStrategyClient()
    try:
        if args.command == "propose":
            result = client.authorize(load_proposal(args.proposal_file))
            rendered = json.dumps(result, indent=2, sort_keys=True)
            if args.output:
                Path(args.output).write_text(rendered + "\n", encoding="utf-8")
            print(rendered)
            return 0 if result.get("authorized") else 1
        if args.command == "cards":
            assigned = [card for card in client.trade_cards(include_terminal=args.include_terminal) if card.get("target_bot") == "sentinel-iron"]
            print(json.dumps({"trade_cards": assigned}, indent=2, sort_keys=True))
            return 0
        if args.command == "feedback":
            payload = json.loads(Path(args.feedback_file).read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("feedback file must contain one JSON object")
            print(json.dumps(client.feedback(payload), indent=2, sort_keys=True))
            return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
