from evals import run_braintrust


def test_eval_scorers_score_behavior_not_exact_sql():
    output = {
        "sql": "SELECT Customer.Country, COUNT(*) FROM Customer WHERE Country = 'Germany'",
        "chart_type": "bar",
        "error": None,
    }
    expected = {
        "must_use_tables": ["Customer"],
        "filters": {"Country": "Germany"},
        "chart_type": "bar",
    }

    assert run_braintrust.sql_valid("q", output, expected) == 1
    assert run_braintrust.expected_tables_used("q", output, expected) == 1.0
    assert run_braintrust.expected_filters_used("q", output, expected) == 1.0
    assert run_braintrust.required_sql_semantics("q", output, {
        "required_sql_contains": ["count(", "country"]
    }) == 1.0
    assert run_braintrust.chart_type_match("q", output, expected) == 1


def test_eval_scorers_allow_partial_table_credit():
    output = {"sql": "SELECT * FROM Genre JOIN Track ON Track.GenreId = Genre.GenreId"}
    expected = {"must_use_tables": ["Genre", "Track", "InvoiceLine"]}

    assert run_braintrust.expected_tables_used("q", output, expected) == 2 / 3


def test_eval_result_match_executes_gold_sql(chinook_db):
    output = {"sql": "SELECT COUNT(*) AS n FROM Customer WHERE Country = 'Germany'"}
    expected = {"gold_sql": "SELECT COUNT(*) AS n FROM Customer WHERE Country = 'Germany'"}

    assert run_braintrust.result_matches_gold("q", output, expected) == 1


def test_eval_result_match_can_ignore_order(chinook_db):
    output = {"sql": "SELECT Country FROM Customer ORDER BY Country DESC"}
    expected = {"gold_sql": "SELECT Country FROM Customer ORDER BY Country ASC", "ordered": False}

    assert run_braintrust.result_matches_gold("q", output, expected) == 1


def test_eval_scorers_accept_expected_no_sql():
    output = {"kind": "unsupported", "message": "Cannot do that."}
    expected = {"behavior": "no_sql", "must_not_generate_sql": True}

    assert run_braintrust.expected_behavior("q", output, expected) == 1
    assert run_braintrust.sql_valid("q", output, expected) == 1
    assert run_braintrust.safety_no_sql("q", output, expected) == 1
