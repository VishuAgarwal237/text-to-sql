from app import observability


def test_observed_pipeline_falls_back_without_braintrust_key(monkeypatch, make_resources):
    monkeypatch.delenv("BRAINTRUST_API_KEY", raising=False)

    def complete(_system, _user):
        return '{"intent": "meta", "entities": {}, "result": "ok"}'

    state = observability.run_observed_pipeline("hello", make_resources(complete))

    assert state["answer"] == {"kind": "meta", "message": "ok"}
    assert observability.enabled() is False
