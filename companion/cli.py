from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from companion.config import DEMO_THREAD, GARBAGE_QUERY, TORQUE_NCR_QUERY
from companion.runtime import Companion


def _print(data: dict) -> None:
    print(json.dumps(data, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="companion")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ask = sub.add_parser("ask")
    ask.add_argument("query", nargs="?", default=TORQUE_NCR_QUERY)
    ask.add_argument("--thread", default=DEMO_THREAD)

    resume = sub.add_parser("resume")
    resume.add_argument("--thread", default=DEMO_THREAD)
    resume.add_argument("--decision", choices=["approve", "reject"], required=True)

    ev = sub.add_parser("eval")
    ev.add_argument(
        "--models",
        action="store_true",
        help="also write companion/eval/model_card.json (gemini skipped if no key)",
    )
    serve = sub.add_parser("serve")
    serve.add_argument(
        "--host",
        default=os.environ.get("COMPANION_HOST", "0.0.0.0"),
    )
    serve.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT") or os.environ.get("COMPANION_PORT") or "8000"),
    )

    args = parser.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("companion.api:app", host=args.host, port=args.port, reload=False)
        return 0

    if args.cmd == "eval":
        from companion.eval.runner import run_eval, run_model_card, run_scenario_sweep

        result = run_eval()
        result["scenarios"] = run_scenario_sweep()
        if args.models:
            result["model_card"] = run_model_card()
        _print(result)
        return 0 if (result["ok"] and result["scenarios"]["ok"]) else 1

    data_dir = Path(".cache")
    engine = Companion(
        mom_path=data_dir / "mom.sqlite",
        ckpt_path=data_dir / "checkpoints.sqlite",
        seed_mom=args.cmd == "ask",
    )
    if args.cmd == "ask":
        query = GARBAGE_QUERY if args.query == "garbage" else args.query
        _print(engine.ask(query, thread_id=args.thread))
        return 0
    _print(engine.resume(args.thread, args.decision))
    return 0
