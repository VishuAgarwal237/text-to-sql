"""Tests for the eval result comparison.

These pin the two things that matter: the scorer must NOT flag correct-but-differently-shaped
results (the false negatives earlier runs hit), and it must still catch genuinely wrong ones.
"""

import unicodedata

from eval.compare import compare_results


def test_row_order_insensitive():
    exp = [{"Name": "Rock", "Sales": 826.65}, {"Name": "Latin", "Sales": 382.14}]
    cand = [{"Name": "Latin", "Sales": 382.14}, {"Name": "Rock", "Sales": 826.65}]
    assert compare_results(exp, cand).passed


def test_alias_and_column_order_insensitive():
    exp = [{"Name": "Rock", "TotalSales": 826.65}]
    cand = [{"revenue": 826.65, "genre": "Rock"}]  # different names + order
    assert compare_results(exp, cand).passed


def test_float_tolerance():
    exp = [{"Avg": 6.66}]
    cand = [{"Avg": 6.659999999999999}]
    assert compare_results(exp, cand).passed


def test_unicode_normalization():
    exp = [{"Name": "Luís"}]
    cand = [{"Name": unicodedata.normalize("NFD", "Luís")}]
    assert compare_results(exp, cand).passed


def test_duplicate_multiplicity_preserved():
    # Two real "Music" playlist rows must not collapse to one.
    exp = [{"Name": "Music", "N": 3290}, {"Name": "Music", "N": 3290}]
    cand = [{"Name": "Music", "N": 3290}]
    assert not compare_results(exp, cand).passed


def test_wrong_number_fails():
    assert not compare_results([{"Total": 449.46}], [{"Total": 449.47}]).passed


def test_missing_and_extra_rows_fail():
    exp = [{"C": "USA", "N": 13}, {"C": "Canada", "N": 8}]
    cand = [{"C": "USA", "N": 13}, {"C": "Mexico", "N": 8}]
    res = compare_results(exp, cand)
    assert not res.passed
    assert res.n_missing == 1 and res.n_extra == 1


def test_null_handling():
    assert compare_results([{"X": None}], [{"X": None}]).passed
    assert not compare_results([{"X": None}], [{"X": 0}]).passed
