import pytest

from hotpath.telemetry.postgres import ActivitySample, parse_activity_output, summarize_activity

OUTPUT = """\
active|1
idle_in_transaction|0
connections|20
commits|15230
wait|Client|ClientRead|0
wait|CPU|running|1
"""


def test_parse_activity_output():
    sample = parse_activity_output(OUTPUT, at=10.0)

    assert sample == ActivitySample(
        at=10.0, active=1, idle_in_transaction=0, connections=20, commits=15230, waits={"CPU:running": 1}
    )


def test_parse_handles_no_wait_rows():
    sample = parse_activity_output("active|0\nidle_in_transaction|0\nconnections|5\ncommits|9\n", at=0.0)

    assert sample.waits == {}
    assert sample.connections == 5


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        parse_activity_output("psql: error: connection refused", at=0.0)


def test_summarize_activity():
    samples = [
        ActivitySample(at=0.0, active=1, idle_in_transaction=0, connections=20, commits=1000, waits={"CPU:running": 1}),
        ActivitySample(at=2.0, active=1, idle_in_transaction=1, connections=20, commits=1180,
                       waits={"Lock:transactionid": 1}),
        ActivitySample(at=4.0, active=2, idle_in_transaction=0, connections=20, commits=1360, waits={"CPU:running": 2}),
    ]

    summary = summarize_activity(samples)

    assert summary.samples == 3
    assert summary.active_connections_avg == pytest.approx(4 / 3, abs=0.01)
    assert summary.active_connections_max == 2
    assert summary.idle_in_transaction_avg == pytest.approx(1 / 3, abs=0.01)
    assert summary.pool_connections_max == 20
    assert summary.commits_per_s == 90.0
    assert summary.wait_events == {"CPU:running": 3, "Lock:transactionid": 1}


def test_summarize_single_sample_has_no_rate():
    summary = summarize_activity([ActivitySample(at=0.0, active=1, idle_in_transaction=0, connections=3, commits=5,
                                                 waits={})])

    assert summary.commits_per_s is None
