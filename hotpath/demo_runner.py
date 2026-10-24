"""GitHub runner -> authenticated live events. Importing this module uses no keys.

Only the coordinator can reserve runs. The workflow must claim that reservation
before loading the model client or executing a benchmark. No visitor-supplied
repo, command, model, callback URL, or patch is accepted.
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class PublishError(RuntimeError):
    def __init__(self, status: int | None):
        self.status = status
        super().__init__(f"Live update was not accepted (HTTP {status or 'unavailable'})")


class Publisher:
    def __init__(self, url: str, secret: str, run_id: str, invocation: str):
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            raise ValueError("DEMO_URL must be an HTTPS origin")
        if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", run_id) or not re.fullmatch(r"\d+:\d+", invocation):
            raise ValueError("Invalid run identity")
        if len(secret) < 32:
            raise ValueError("DEMO_CALLBACK_SECRET must have at least 32 characters")
        self.url = url.rstrip("/") + "/api/demo/update"
        self.secret, self.run_id, self.invocation = secret, run_id, invocation
        self.sequence = 0

    def send(self, kind: str, **data) -> None:
        payload = json.dumps({"type": kind, "run_id": self.run_id, "invocation": self.invocation, **data}).encode()
        # A retry keeps the same sequence number; the coordinator deduplicates it.
        for attempt in range(3):
            request = Request(self.url, data=payload, method="POST", headers={
                "Authorization": f"Bearer {self.secret}", "Content-Type": "application/json",
                "User-Agent": "HotPath-runner",
            })
            try:
                with urlopen(request, timeout=15) as response:
                    response.read()
                return
            except HTTPError as error:
                if error.code < 500 or attempt == 2:
                    raise PublishError(error.code) from None
            except (URLError, TimeoutError):
                if attempt == 2:
                    raise PublishError(None) from None
            time.sleep(attempt + 1)

    def event(self, event) -> None:
        self.send("event", sequence=self.sequence, event=event.model_dump(mode="json"))
        self.sequence += 1

    def fail(self) -> None:
        try:
            self.send("finish", state="failed")
        except PublishError as error:
            if error.status != 409:
                raise
            self.send("setup_failed")


def run(publisher: Publisher, seed: int, failure: str = "random") -> None:
    # This acknowledgement is required even on manual workflow dispatch/reruns.
    publisher.send("claim", seed=seed)
    from hotpath.agent.state import Budget, Event, Phase
    from hotpath.agent.store import InvestigationStore
    from hotpath.challenges import generate_challenge
    from hotpath.cli import record_investigation
    from hotpath.models.nemotron import NemotronClient

    challenge = generate_challenge(seed, family=None if failure == "random" else failure)
    store = InvestigationStore.create(challenge.repo)
    event = Event(phase=Phase.ANALYZE_REPOSITORY, kind="challenge", message="Fresh benchmark case generated", data=challenge.public)
    store.record(event)
    publisher.event(event)
    client = NemotronClient()
    if not client.model:
        raise RuntimeError("NEMOTRON_MODEL is required")
    outcome, _ = record_investigation(
        challenge.repo, client,
        Budget(max_hypotheses=2, max_experiments=3, max_patch_rounds=1, candidates_per_round=2),
        store=store, on_record=publisher.event,
        warmup="5s", duration="10s", race_repeats=3, verify_runs=7,
    )
    # 'done' means the investigation ended, not that a fix passed. The phase
    # events and verification report retain the actual outcome, including failure.
    publisher.send("finish", state="done", diff=outcome.diff)


def main() -> int:
    publisher = Publisher(os.environ["DEMO_URL"], os.environ["DEMO_CALLBACK_SECRET"],
                          os.environ["DEMO_RUN_ID"], f"{os.environ['GITHUB_RUN_ID']}:{os.environ['GITHUB_RUN_ATTEMPT']}")
    if sys.argv[1:] == ["--failed"]:
        publisher.fail()
        return 0
    seed_text = os.environ["DEMO_SEED"]
    if not re.fullmatch(r"\d{1,10}", seed_text) or int(seed_text) > 2**32 - 1:
        raise ValueError("Invalid challenge seed")
    failure = os.environ.get("DEMO_FAILURE", "random")
    if failure not in {"random", "checkout", "catalog"}:
        raise ValueError("Invalid failure mode")
    try:
        run(publisher, int(seed_text), failure)
    except Exception:
        # Full evidence stays in artifacts. Do not echo environment values or an
        # HTTP response that might contain sensitive details into the public feed.
        try:
            publisher.fail()
        except PublishError:
            pass
        print("Investigation stopped; inspect the workflow and saved evidence.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
