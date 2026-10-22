"""Command line: ``tn-screener serve | screen | verify | sources fetch | sources check``."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from . import engine, rules, sources


def cmd_screen(args) -> int:
    household = json.load(open(args.file, encoding="utf-8") if args.file != "-" else sys.stdin)
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    print(json.dumps(engine.screen(household, as_of), indent=2))
    return 0


def cmd_verify(args) -> int:
    problems = rules.verify()
    for rule_id, ps in problems.items():
        for p in ps:
            print(f"{rule_id}: {p}")
    print("all rules check out against their sources" if not problems else f"{len(problems)} rules have problems")
    return 1 if problems else 0


def cmd_sources(args) -> int:
    reports = sources.fetch(write=args.action == "fetch")
    status = 0
    for r in reports:
        if r.get("error"):
            print(f"{r['id']}: FAILED {r['error']}")
            status = 1
        elif r["changed"]:
            print(f"{r['id']}: changed upstream" if args.action == "check" else f"{r['id']}: updated")
            status = 1 if args.action == "check" else status
    today = date.today()
    for r in rules.load().values():
        if r.effective_to and r.effective_to < today:
            note = " (still used, with a warning)" if r.carry_forward else ""
            print(f"rule {r.id} expired {r.effective_to}{note}")
            status = 1
    if args.action == "fetch":
        problems = rules.verify()
        for rule_id, ps in problems.items():
            print(f"rule {rule_id}: " + "; ".join(ps))
        status = 1 if problems else status
    if status == 0:
        print("sources unchanged and every rule is current")
    return status


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tn-screener", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="run the MCP server on stdio")
    s = sub.add_parser("screen", help="screen a household given as JSON (a file, or - for stdin)")
    s.add_argument("file")
    s.add_argument("--as-of", help="YYYY-MM-DD (default today)")
    sub.add_parser("verify", help="check every rule's quotes and numbers against the source texts")
    src = sub.add_parser("sources", help="refresh the official source texts")
    src.add_argument("action", choices=["fetch", "check"],
                     help="fetch: download and update; check: download and report changes only")
    args = p.parse_args(argv)
    if args.cmd == "serve":
        from .server import main as serve

        serve()
        return 0
    return {"screen": cmd_screen, "verify": cmd_verify, "sources": cmd_sources}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
