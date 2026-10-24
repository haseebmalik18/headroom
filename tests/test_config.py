from pathlib import Path

import pytest

from headroom.config import load_config, parse_duration

CHECKOUT = Path(__file__).resolve().parents[1] / "examples" / "checkout-service"


def test_load_checkout_service_config():
    config = load_config(CHECKOUT)

    assert config.service == "checkout-service"
    assert config.objective.endpoint == "POST /inventory/reserve"
    assert config.objective.metric == "p99_ms"
    assert config.objective.target == 100
    assert config.constraints.max_error_rate == 0.001
    assert config.workload.concurrency == 500
    assert config.runtime.app_service == "app"
    assert config.runtime.load_script == "/load/reserve.js"


def test_missing_config_raises_helpful_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="headroom.yaml"):
        load_config(tmp_path)


@pytest.mark.parametrize(
    "text, seconds",
    [("10s", 10.0), ("1.5s", 1.5), ("500ms", 0.5), ("2m", 120.0)],
)
def test_parse_duration(text, seconds):
    assert parse_duration(text) == seconds


def test_parse_duration_rejects_garbage():
    with pytest.raises(ValueError):
        parse_duration("ten seconds")
