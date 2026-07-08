import pytest

from app import llm


def test_parse_plain_json():
    assert llm.parse_json('{"a": 1}') == {"a": 1}


def test_parse_fenced_json():
    assert llm.parse_json('```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}


def test_parse_json_with_surrounding_prose():
    assert llm.parse_json('Here you go: {"b": 3} — done') == {"b": 3}


def test_parse_json_array():
    assert llm.parse_json("```\n[1, 2, 3]\n```") == [1, 2, 3]


def test_parse_json_raises_when_absent():
    with pytest.raises(ValueError):
        llm.parse_json("no json here at all")
