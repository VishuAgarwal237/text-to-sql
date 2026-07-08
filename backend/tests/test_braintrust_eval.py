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
    assert run_braintrust.chart_type_match("q", output, expected) == 1


def test_eval_scorers_allow_partial_table_credit():
    output = {"sql": "SELECT * FROM Genre JOIN Track ON Track.GenreId = Genre.GenreId"}
    expected = {"must_use_tables": ["Genre", "Track", "InvoiceLine"]}

    assert run_braintrust.expected_tables_used("q", output, expected) == 2 / 3
