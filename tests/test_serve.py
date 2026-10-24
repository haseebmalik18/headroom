import json
import threading
import time

import httpx

from hotpath.serve import follow, make_server


def test_follow_yields_lines_appended_later_and_stops_when_done(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text('{"n": 1}\n')
    finished = threading.Event()

    def writer():
        time.sleep(0.1)
        with path.open("a") as f:
            f.write('{"n": 2}\n{"n": ')   # a half-written line is held back until it is complete
        time.sleep(0.1)
        with path.open("a") as f:
            f.write('3}\n')
        finished.set()

    threading.Thread(target=writer).start()
    lines = list(follow(path, finished.is_set, poll=0.02))

    assert [json.loads(line)["n"] for line in lines] == [1, 2, 3]


def _investigation(root, name, events, done=True):
    path = root / name
    path.mkdir(parents=True)
    (path / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    if done:
        (path / "outcome.json").write_text("{}")
    return path


def test_streams_an_investigation_as_server_sent_events(tmp_path):
    root = tmp_path / "investigations"
    _investigation(root, "20261023-000000-auth-service", [{"kind": "phase", "message": "old"}])
    _investigation(root, "20261024-000000-auth-service", [{"kind": "phase", "message": "a"}, {"kind": "baseline", "message": "b"}])
    server = make_server(0, root=root, dist=None)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        listing = httpx.get(f"{base}/api/investigations").json()
        with httpx.stream("GET", f"{base}/api/live", params={"id": "latest"}, timeout=5) as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            body = "".join(response.iter_text())
    finally:
        server.shutdown()

    assert listing[0] == "20261024-000000-auth-service"
    data = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: {\"kind")]
    assert [e["message"] for e in data] == ["a", "b"]
    assert "event: done" in body


def test_empty_server_is_available_before_first_run(tmp_path):
    server = make_server(0, root=tmp_path / "investigations")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        response = httpx.get(f"http://127.0.0.1:{server.server_address[1]}/api/investigations")
        assert response.status_code == 200
        assert response.json() == []
        assert response.headers["cache-control"] == "no-store"
    finally:
        server.shutdown()
        server.server_close()


def test_reconnect_resumes_events_and_includes_final_patch(tmp_path):
    path = _investigation(tmp_path, "run", [{"kind": "phase", "message": "first"},
                                             {"kind": "phase", "message": "second"}])
    (path / "outcome.json").write_text(json.dumps({"winner": "fix", "diff": "verified patch", "context": "private"}))
    server = make_server(0, root=tmp_path)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        response = httpx.get(f"http://127.0.0.1:{server.server_address[1]}/api/live?id=run",
                             headers={"Last-Event-ID": "0"})
        assert '"first"' not in response.text
        assert 'id: 1\ndata: {"kind": "phase", "message": "second"}' in response.text
        assert 'event: done\ndata: {"winner": "fix", "diff": "verified patch"}' in response.text
        assert "private" not in response.text
        assert response.headers["x-accel-buffering"] == "no"
    finally:
        server.shutdown()
        server.server_close()


def test_stream_delivers_events_written_after_browser_connects(tmp_path):
    path = _investigation(tmp_path, "running", [{"kind": "phase", "message": "started"}], done=False)
    server = make_server(0, root=tmp_path)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with httpx.stream("GET", f"http://127.0.0.1:{server.server_address[1]}/api/live?id=running", timeout=5) as response:
            lines = response.iter_lines()
            # The first event reaches the client while the investigation is still running.
            while True:
                line = next(lines)
                if line.startswith('data: {"kind"'):
                    assert "started" in line
                    break
            assert not (path / "outcome.json").exists()
            with (path / "events.jsonl").open("a") as f:
                f.write(json.dumps({"kind": "phase", "message": "finished"}) + "\n")
            (path / "outcome.json").write_text('{"winner": null, "diff": null}')
            remainder = "\n".join(lines)
            assert '"finished"' in remainder
            assert "event: done" in remainder
    finally:
        server.shutdown()
        server.server_close()
