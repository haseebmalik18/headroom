import json
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest

from headroom.agent.state import Event, Phase
from headroom.demo_runner import Publisher, PublishError, run

RUN = "11111111-1111-4111-8111-111111111111"


def publisher():
    return Publisher("https://demo.example", "s" * 40, RUN, "123:1")


def test_publish_retry_preserves_event_sequence(monkeypatch):
    requests = []

    def send(request, **kwargs):
        requests.append(json.loads(request.data))
        if len(requests) == 1:
            raise URLError("connection lost after acceptance")
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    monkeypatch.setattr("headroom.demo_runner.urlopen", send)
    monkeypatch.setattr("headroom.demo_runner.time.sleep", lambda _: None)
    p = publisher()
    p.event(Event(phase=Phase.BASELINE, kind="phase", message="Measuring"))
    assert requests[0] == requests[1]
    assert requests[0]["sequence"] == 0
    assert p.sequence == 1
    assert "s" * 40 not in json.dumps(requests)


def test_rejected_claim_never_generates_case_or_loads_client(monkeypatch):
    p = publisher()
    monkeypatch.setattr(p, "send", Mock(side_effect=PublishError(409)))
    generate = Mock()
    monkeypatch.setattr("headroom.challenges.generate_challenge", generate)
    with pytest.raises(PublishError):
        run(p, 42)
    generate.assert_not_called()


def test_unauthorized_callback_is_not_retried(monkeypatch):
    send = Mock(side_effect=HTTPError("https://demo.example", 401, "Unauthorized", {}, None))
    monkeypatch.setattr("headroom.demo_runner.urlopen", send)
    with pytest.raises(PublishError):
        publisher().send("claim", seed=42)
    assert send.call_count == 1


@pytest.mark.parametrize("url", ["http://demo.example", "https://user@demo.example", "https://demo.example/other", "https://demo.example?secret=x"])
def test_callback_is_an_https_origin(url):
    with pytest.raises(ValueError):
        Publisher(url, "s" * 40, RUN, "123:1")
