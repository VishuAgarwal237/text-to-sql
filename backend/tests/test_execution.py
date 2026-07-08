import pytest

from app import db, execution
from app.execution import QueryCostError


# --- LIMIT injection (pure sqlglot, no DB) --------------------------------------------------
def test_ensure_limit_adds_when_missing():
    out = execution.ensure_limit("SELECT Name FROM Genre", 50)
    assert "LIMIT 50" in out.upper()


def test_ensure_limit_tightens_oversized():
    out = execution.ensure_limit("SELECT Name FROM Genre LIMIT 10000", 100)
    assert "LIMIT 100" in out.upper()
    assert "10000" not in out


def test_ensure_limit_keeps_smaller_existing():
    out = execution.ensure_limit("SELECT Name FROM Genre LIMIT 5", 100)
    assert "LIMIT 5" in out.upper()


def test_ensure_limit_preserves_inner_limit():
    sql = "SELECT * FROM (SELECT Name FROM Genre LIMIT 3)"
    out = execution.ensure_limit(sql, 100)
    assert "LIMIT 3" in out.upper()  # subquery limit untouched
    assert out.upper().count("LIMIT") == 2  # outer limit added


# --- cost check -----------------------------------------------------------------------------
def test_check_cost_reports_scans(chinook_db):
    info = execution.check_cost("SELECT Name FROM Genre")
    assert info["full_scans"] >= 1
    assert "plan" in info


def test_check_cost_rejects_over_budget(chinook_db, monkeypatch):
    monkeypatch.setattr(execution, "MAX_FULL_SCANS", 0)
    with pytest.raises(QueryCostError):
        execution.check_cost("SELECT Name FROM Genre")


# --- run_guarded happy paths ----------------------------------------------------------------
def test_run_guarded_executes_and_limits(chinook_db):
    res = execution.run_guarded("SELECT Name FROM Genre ORDER BY Name", max_rows=10)
    assert res["columns"] == ["Name"]
    assert {r["Name"] for r in res["rows"]} == {"Latin", "Rock"}
    assert res["guards"]["limit_applied"] == 10
    assert "LIMIT" in res["guards"]["executed_sql"].upper()


def test_run_guarded_row_cap_truncates(chinook_db):
    res = execution.run_guarded("SELECT Name FROM Genre", max_rows=1)
    assert res["row_count"] == 1
    assert res["truncated"] is True


def test_run_guarded_rejects_write(chinook_db):
    with pytest.raises(db.UnsafeSQLError):
        execution.run_guarded("DELETE FROM Genre")
