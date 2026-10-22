"""Run the eval conversations: Claude as the navigator, a cheaper model as the person.

Two arms share the same interview instructions (the plugin's skill):

  tools     Claude with the screener's MCP tools and nothing else
  baseline  Claude with web search and fetch instead, told to find the
            official rules itself

Each case is a multi-turn conversation. The person is simulated from the
case's fact sheet: it answers only what it's asked and says [DONE] once it
has its answer. Calls go through the ``claude`` CLI in print mode, one
session per conversation (``--session-id`` then ``--resume``). Set
TN_EVAL_USE_LOGIN=1 to drop ANTHROPIC_API_KEY and use the CLI's login.

Every conversation is saved as JSON under evals/runs/<run>/<arm>/<case>.json;
re-running the same command skips finished ones.

    uv run python evals/run.py --run 2026-10-22 --arms tools baseline --cases clear-usda-family
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SKILL = ROOT / "plugin" / "skills" / "benefits-navigator" / "SKILL.md"
AS_OF = "2026-10-22"
MAX_TURNS = 7
TOOLS = ["mcp__tn-benefits__screen_household", "mcp__tn-benefits__search_policy", "mcp__tn-benefits__get_rule"]

BASELINE_RULE = """\
## The one hard rule

You don't have a screening tool. Before telling someone whether they might qualify, use
web search to find the current official Tennessee and federal rules (income limits,
deductions, benefit amounts) and work it out carefully from them. Cite the official
pages you used, with links."""

SIM_SYSTEM = """\
You are role-playing a person in a text chat with a benefits helper. Stay in character.

Your situation (the only facts you know):
{facts}

How to behave:
- You already sent your first message. Now reply to the helper's latest message.
- Answer only what you're asked, briefly and casually, like a real person texting. Don't
  volunteer facts you weren't asked about.
- If asked something your situation doesn't cover, say you're not sure or give a plausible
  "no" (e.g. no other income, no other bills).
- Write in {language}.
- When the helper has given you their answer about what you might qualify for and isn't
  asking you anything else, reply with exactly: [DONE]
- Never mention that you are role-playing."""


def skill_body(arm: str) -> str:
    text = SKILL.read_text(encoding="utf-8")
    body = text.split("---", 2)[2].strip()
    if arm == "baseline":
        body = re.sub(r"## The one hard rule\n.*?(?=\n## )", BASELINE_RULE + "\n", body, flags=re.S)
        body = body.replace("call `screen_household`", "work it out").replace("`search_policy`", "web search")
        body = re.sub(r"- Give the next steps from `next_steps`:", "- Give the next steps:", body)
        body = body.replace("from `citations`", "you found").replace("Don't cite anything the tool didn't "
                                                                     "return.", "Only cite pages you opened.")
    return f"Today is {AS_OF}.\n\n{body}"


def env() -> dict:
    e = dict(os.environ)
    if os.environ.get("TN_EVAL_USE_LOGIN"):
        e.pop("ANTHROPIC_API_KEY", None)
    return e


BASE = ["--setting-sources", "", "--disable-slash-commands", "--strict-mcp-config"]


async def claude(argv: list[str], timeout: float) -> tuple[list[dict], str]:
    proc = await asyncio.create_subprocess_exec(
        "claude", *argv, env=env(), cwd=str(ROOT), stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"timed out after {timeout:.0f}s") from None
    events = []
    for line in out.decode(errors="replace").splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    return events, err.decode(errors="replace")


def agent_argv(arm: str, model: str, mcp_config: Path) -> list[str]:
    argv = ["-p", "--model", model, "--output-format", "stream-json", "--verbose",
            "--system-prompt", skill_body(arm), *BASE]
    if arm == "tools":
        return argv + ["--tools", "", "--mcp-config", str(mcp_config), "--allowedTools", ",".join(TOOLS)]
    return argv + ["--mcp-config", '{"mcpServers":{}}', "--tools", "WebSearch,WebFetch",
                   "--allowedTools", "WebSearch,WebFetch"]


def summarize(events: list[dict]) -> dict:
    """The parts of one agent turn the scorer needs."""
    turn = {"text": "", "tool_calls": [], "cost_usd": 0.0, "duration_ms": 0, "error": None, "model": None}
    pending = {}
    for e in events:
        if e.get("type") == "assistant":
            for c in e["message"].get("content", []):
                if c.get("type") == "tool_use":
                    call = {"name": c["name"], "input": c.get("input"), "result": None}
                    pending[c["id"]] = call
                    turn["tool_calls"].append(call)
        elif e.get("type") == "user":
            for c in e["message"].get("content", []) if isinstance(e["message"].get("content"), list) else []:
                if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in pending:
                    content = c.get("content")
                    if isinstance(content, list):
                        content = "".join(x.get("text", "") for x in content if isinstance(x, dict))
                    pending[c["tool_use_id"]]["result"] = content
                    pending[c["tool_use_id"]]["is_error"] = bool(c.get("is_error"))
        elif e.get("type") == "result":
            turn["text"] = e.get("result") or ""
            turn["cost_usd"] = e.get("total_cost_usd") or 0.0
            turn["duration_ms"] = e.get("duration_ms") or 0
            turn["model"] = next(iter(e.get("modelUsage") or {}), None)
            if e.get("is_error"):
                turn["error"] = str(e.get("result"))[:500]
    if not any(e.get("type") == "result" for e in events):
        turn["error"] = "no result event"
    return turn


def transcript_text(messages: list[dict]) -> str:
    return "\n\n".join(f"{'PERSON' if m['role'] == 'user' else 'HELPER'}: {m['text']}" for m in messages)


async def simulate_user(case: dict, messages: list[dict], model: str) -> tuple[str, float]:
    language = "Spanish" if case["lang"] == "es" else "English"
    system = SIM_SYSTEM.format(facts="\n".join(f"- {f}" for f in case["facts"]), language=language)
    prompt = (f"The conversation so far:\n\n{transcript_text(messages)}\n\n"
              "Write your next message as the PERSON (just the message text).")
    events, err = await claude(["-p", "--model", model, "--output-format", "stream-json", "--verbose",
                                "--system-prompt", system, "--tools", "", *BASE,
                                "--mcp-config", '{"mcpServers":{}}', "--no-session-persistence", prompt], 180)
    t = summarize(events)
    if t["error"]:
        raise RuntimeError(f"simulated user failed: {t['error']} {err[:300]}")
    return t["text"].strip(), t["cost_usd"]


async def converse(case: dict, arm: str, args, mcp_config: Path) -> dict:
    session = str(uuid.uuid4())
    messages = [{"role": "user", "text": case["opening"]}]
    turns, sim_cost = [], 0.0
    started = time.time()
    status = "max_turns"
    for i in range(MAX_TURNS):
        argv = agent_argv(arm, args.model, mcp_config)
        argv += ["--session-id", session] if i == 0 else ["--resume", session]
        events, err = await claude(argv + [messages[-1]["text"]], args.timeout)
        turn = summarize(events)
        if turn["error"]:
            turn["stderr"] = err[-500:]
        turns.append(turn)
        messages.append({"role": "assistant", "text": turn["text"]})
        if turn["error"]:
            status = "error"
            break
        reply, cost = await simulate_user(case, messages, args.sim_model)
        sim_cost += cost
        if "[DONE]" in reply:
            status = "done"
            break
        messages.append({"role": "user", "text": reply})
    return {
        "case": case["id"], "arm": arm, "model": args.model, "sim_model": args.sim_model, "status": status,
        "messages": messages, "turns": turns,
        "agent_cost_usd": round(sum(t["cost_usd"] for t in turns), 4), "sim_cost_usd": round(sim_cost, 4),
        "wall_seconds": round(time.time() - started, 1),
    }


async def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", required=True, help="run name (a folder under evals/runs)")
    p.add_argument("--arms", nargs="+", default=["tools", "baseline"], choices=["tools", "baseline"])
    p.add_argument("--cases", nargs="*", help="case ids (default all)")
    p.add_argument("--model", default="sonnet")
    p.add_argument("--sim-model", default="haiku")
    p.add_argument("--concurrency", type=int, default=3)
    p.add_argument("--timeout", type=float, default=600)
    args = p.parse_args()

    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    if args.cases:
        unknown = set(args.cases) - {c["id"] for c in cases}
        if unknown:
            p.error(f"unknown cases: {sorted(unknown)}")
        cases = [c for c in cases if c["id"] in args.cases]
    out_dir = HERE / "runs" / args.run
    mcp_config = out_dir / "mcp.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    mcp_config.write_text(json.dumps({"mcpServers": {"tn-benefits": {
        "command": "uv", "args": ["run", "--project", str(ROOT), "tn-screener", "serve"]}}}))

    jobs = [(c, a) for a in args.arms for c in cases if not (out_dir / a / f"{c['id']}.json").exists()]
    print(f"{len(jobs)} conversations to run", file=sys.stderr)
    sem = asyncio.Semaphore(args.concurrency)

    async def job(case, arm):
        async with sem:
            try:
                rec = await converse(case, arm, args, mcp_config)
            except Exception as e:  # noqa: BLE001 - record and move on
                print(f"{arm}/{case['id']}: FAILED {e}", file=sys.stderr)
                return
            path = out_dir / arm / f"{case['id']}.json"
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
            print(f"{arm}/{case['id']}: {rec['status']}, {len(rec['turns'])} turns, "
                  f"${rec['agent_cost_usd']:.3f}, {rec['wall_seconds']}s", file=sys.stderr)

    await asyncio.gather(*(job(c, a) for c, a in jobs))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
