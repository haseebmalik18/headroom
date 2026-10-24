from pathlib import Path

import pytest
import yaml

from headroom.config import Objective, load_config, parse_duration

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


def test_latency_goals_are_met_below_the_target():
    goal = Objective(endpoint="GET /x", metric="p99_ms", target=100)

    assert goal.met(99.9) and not goal.met(100)
    assert goal.better(20, 30)
    assert goal.text() == "p99 latency under 100 ms"
    assert goal.show(1858.4) == "1,858 ms"


def test_throughput_goals_are_met_at_or_above_the_target():
    goal = Objective(endpoint="POST /x", metric="throughput_rps", target=240)

    assert goal.met(240) and not goal.met(239.9)
    assert goal.better(250, 186)
    assert goal.text() == "throughput of at least 240 req/s"
    assert goal.show(186.04) == "186 req/s"


def test_error_rate_goals_read_as_percentages():
    goal = Objective(endpoint="GET /x", metric="error_rate", target=0.001)

    assert goal.met(0.0005) and not goal.met(0.002)
    assert goal.text() == "error rate under 0.1%"
    assert goal.show(0.0213) == "2.13%"


def test_a_config_can_set_several_objectives(tmp_path):
    config = yaml.safe_load(CHECKOUT.joinpath("headroom.yaml").read_text())
    del config["objective"]
    config["objectives"] = [{"endpoint": "POST /inventory/reserve", "metric": "p99_ms", "target": 100},
                            {"endpoint": "GET /products", "metric": "p99_ms", "target": 50}]
    (tmp_path / "headroom.yaml").write_text(yaml.safe_dump(config))

    loaded = load_config(tmp_path)

    assert [o.endpoint for o in loaded.objectives] == ["POST /inventory/reserve", "GET /products"]
    assert loaded.objective.endpoint == "POST /inventory/reserve"      # the first one is the primary


def test_a_single_objective_still_works():
    config = load_config(CHECKOUT)

    assert len(config.objectives) == 1
    assert config.objective.target == 100
