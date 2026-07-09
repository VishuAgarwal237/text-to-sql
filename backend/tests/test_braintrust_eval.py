from evals import run_braintrust


def test_load_cases_accepts_evaluation_data_json(tmp_path):
    path = tmp_path / "evaluation_data.json"
    path.write_text(
        """
        [
          {
            "question": "Top genres?",
            "gold_sql": "SELECT Name FROM Genre",
            "expected_rows": [{"Name": "Rock"}]
          }
        ]
        """
    )

    cases = run_braintrust.load_cases(path)

    assert cases == [{
        "input": "Top genres?",
        "expected": {
            "gold_sql": "SELECT Name FROM Genre",
            "expected_rows": [{"Name": "Rock"}],
        },
    }]


def test_load_cases_accepts_attached_evaluation_data_shape(tmp_path):
    path = tmp_path / "evaluation_data.json"
    path.write_text(
        """
        [
          {
            "question": "Albums by AC/DC",
            "sql": "SELECT Title FROM Album",
            "expected_result": [{"Title": "For Those About To Rock"}]
          }
        ]
        """
    )

    cases = run_braintrust.load_cases(path)

    assert cases == [{
        "input": "Albums by AC/DC",
        "expected": {
            "gold_sql": "SELECT Title FROM Album",
            "expected_rows": [{"Title": "For Those About To Rock"}],
        },
    }]


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


def test_eval_result_match_uses_labeled_expected_rows(chinook_db):
    output = {"sql": "SELECT COUNT(*) AS n FROM Customer WHERE Country = 'Germany'"}
    expected = {"expected_rows": [{"n": 1}]}

    assert run_braintrust.result_matches_gold("q", output, expected) == 1


def test_eval_result_match_can_ignore_order(chinook_db):
    output = {"sql": "SELECT Country FROM Customer ORDER BY Country DESC"}
    expected = {"gold_sql": "SELECT Country FROM Customer ORDER BY Country ASC", "ordered": False}

    assert run_braintrust.result_matches_gold("q", output, expected) == 1


def test_eval_result_match_allows_reordered_metric_ties(chinook_db):
    output = {"sql": "SELECT Country, COUNT(*) AS n FROM Customer GROUP BY Country ORDER BY n DESC, Country ASC"}
    expected = {
        "gold_sql": "SELECT Country, COUNT(*) AS n FROM Customer GROUP BY Country ORDER BY n DESC, Country DESC",
    }

    assert run_braintrust.result_matches_gold("q", output, expected) == 1


def test_eval_result_match_rejects_wrong_metric_order(chinook_db):
    output = {"sql": "SELECT InvoiceId, Total FROM Invoice ORDER BY Total ASC"}
    expected = {
        "gold_sql": "SELECT InvoiceId, Total FROM Invoice ORDER BY Total DESC",
    }

    assert run_braintrust.result_matches_gold("q", output, expected) == 0


def test_eval_scorers_accept_expected_no_sql():
    output = {"kind": "unsupported", "message": "Cannot do that."}
    expected = {"behavior": "no_sql", "must_not_generate_sql": True}

    assert run_braintrust.expected_behavior("q", output, expected) == 1
    assert run_braintrust.sql_valid("q", output, expected) == 1
    assert run_braintrust.safety_no_sql("q", output, expected) == 1
    assert run_braintrust.answer_accuracy("q", output, expected) == 1
    assert run_braintrust.sql_precision("q", output, expected) is None


def test_sql_precision_scores_false_positive_sql_for_no_sql_case():
    output = {"kind": "analytical_sql", "sql": "SELECT * FROM Customer"}
    expected = {"behavior": "no_sql", "must_not_generate_sql": True}

    assert run_braintrust.answer_accuracy("q", output, expected) == 0
    assert run_braintrust.sql_precision("q", output, expected) == 0.0


def test_answer_accuracy_and_precision_use_result_correctness(chinook_db):
    output = {"sql": "SELECT COUNT(*) AS n FROM Customer WHERE Country = 'Germany'", "error": None}
    expected = {
        "must_use_tables": ["Customer"],
        "filters": {"Country": "Germany"},
        "required_sql_contains": ["count(", "germany"],
        "expected_rows": [{"n": 1}],
    }

    assert run_braintrust.answer_accuracy("q", output, expected) == 1
    assert run_braintrust.sql_precision("q", output, expected) == 1.0
