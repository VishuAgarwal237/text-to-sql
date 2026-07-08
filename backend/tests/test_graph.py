"""The LangGraph adapter must produce the same answers as the plain-Python runner — it adds
orchestration, not behaviour. Skipped if langgraph isn't installed."""

import pytest

pytest.importorskip("langgraph")

from app import graph  # noqa: E402
from tests.conftest import FakeLLM, j  # noqa: E402
from tests.test_nodes import _GOOD_SQL, _HYDRATION, _PRESENTATION  # noqa: E402


def test_graph_analytical_path(chinook_db, make_resources):
    llm = FakeLLM({
        "router": j({"intent": "analytical_sql", "entities": {}, "result": ""}),
        "hydration": _HYDRATION,
        "sql": j({"sql": _GOOD_SQL, "assumptions": []}),
        "presentation": _PRESENTATION,
    })
    answer = graph.run("top selling genres by revenue", make_resources(llm))
    assert answer["kind"] == "analytical_sql"
    assert answer["rows"][0]["Name"] == "Rock"
    assert answer["chart_type"] == "bar"


def test_graph_meta_path(chinook_db, make_resources):
    llm = FakeLLM({"router": j({"intent": "meta", "entities": {}, "result": "Hi there."})})
    answer = graph.run("hello", make_resources(llm))
    assert answer == {"kind": "meta", "message": "Hi there."}


def test_graph_repair_loop(chinook_db, make_resources):
    llm = FakeLLM({
        "router": j({"intent": "analytical_sql", "entities": {}, "result": ""}),
        "hydration": _HYDRATION,
        "sql": j({"sql": "SELECT Nope FROM Genre"}),
        "repair": j({"sql": "SELECT Name FROM Genre ORDER BY Name"}),
        "presentation": _PRESENTATION,
    })
    answer = graph.run("list genres", make_resources(llm))
    assert answer["sql"] == "SELECT Name FROM Genre ORDER BY Name"
