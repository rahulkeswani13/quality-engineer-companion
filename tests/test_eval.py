from companion.eval.runner import run_eval, run_model_card


def test_gold_eval_passes_on_local_provider():
    result = run_eval()
    assert result["ok"], result["failures"]


def test_model_card_skips_gemini_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    def fake_sweep(**_kwargs):
        return {"ok": True, "n": 10, "failures": [], "fallback_count": 0}

    monkeypatch.setattr("companion.eval.runner.run_scenario_sweep", fake_sweep)
    path = tmp_path / "model_card.json"
    card = run_model_card(path)
    assert card["ok"] is True
    gem = next(m for m in card["models"] if m["provider"] == "gemini")
    assert gem.get("skipped") is True
    local = next(m for m in card["models"] if m["provider"] == "local")
    assert local["contract_ok"] is True
    assert path.is_file()
