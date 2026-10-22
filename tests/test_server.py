"""Tool calls through an in-process MCP client."""

import dataclasses
import json

import pytest
from mcp import Client

from tn_screener import engine
from tn_screener.server import HouseholdIn, IncomeIn, PersonIn, build_server

# anyio's plugin runs fixture setup, test and teardown in one task, which the
# MCP client's cancel scopes require.
pytestmark = pytest.mark.anyio


def result_of(r):
    if r.structured_content is not None:
        sc = r.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    return json.loads(r.content[0].text) if not r.is_error else r.content[0].text


@pytest.fixture
async def call():
    async with Client(build_server()) as client:
        async def _call(tool, args=None):
            r = await client.call_tool(tool, args or {})
            return r.is_error, result_of(r)
        yield _call


async def test_tools_are_listed_read_only():
    async with Client(build_server()) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {"screen_household", "search_policy", "get_rule"}
    assert all(t.annotations.read_only_hint for t in tools.values())
    schema = json.dumps(tools["screen_household"].input_schema)
    assert "buys and cooks food together" in schema  # field descriptions reach the model


async def test_screen_household(call):
    err, out = await call("screen_household", {
        "household": {"members": [{"age": 30, "label": "you"}, {"age": 2, "label": "your daughter"}],
                      "income": [{"amount": 450, "frequency": "weekly"}], "rent_or_mortgage": 750,
                      "utilities": "heating_cooling"},
        "as_of": "2026-10-22"})
    assert not err
    assert out["programs"]["snap"]["status"] == "likely"
    assert out["programs"]["wic"]["status"] == "likely"
    assert "your daughter" in out["programs"]["wic"]["summary"]
    assert out["citations"]["snap.gross_limit"]["sources"][0]["url"].startswith("https://www.fns.usda.gov")


async def test_screen_errors_are_readable(call):
    err, msg = await call("screen_household", {"household": {"members": []}, "as_of": "2026-10-22"})
    assert err and "at least one member" in msg
    err, msg = await call("screen_household", {"household": {"members": [{"age": 30}]}, "as_of": "2030-01-01"})
    assert err and "expired" in msg


async def test_search_policy(call):
    err, hits = await call("search_policy", {"query": "vehicle excluded resource", "program": "snap"})
    assert not err and hits and hits[0]["official"]
    assert "vehicle" in hits[0]["text"].lower()
    err, hits = await call("search_policy", {"query": "200% broad-based Tennessee", "official_only": False})
    assert any(not h["official"] for h in hits)


async def test_get_rule(call):
    err, listing = await call("get_rule")
    assert not err and "snap.gross_limit" in listing["rules"]
    err, r = await call("get_rule", {"rule_id": "snap.gross_limit_200_reported"})
    assert r["status"] == "reported" and r["contradicted_by"]
    err, msg = await call("get_rule", {"rule_id": "nope"})
    assert err and "unknown rule" in msg


def test_tool_schema_matches_the_engine():
    for model, dc in ((PersonIn, engine.Person), (IncomeIn, engine.Income), (HouseholdIn, engine.Household)):
        assert set(model.model_fields) == {f.name for f in dataclasses.fields(dc)}, model.__name__
