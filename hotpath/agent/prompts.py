"""Prompts for NVIDIA Nemotron.

The model never sees raw tool output dumps; HotPath renders compact, numeric
evidence. The model is asked for testable claims, not for verdicts on its own fixes.
"""

SYSTEM = """You are HotPath, an autonomous performance engineer investigating a production SLO violation.

You work like a careful scientist:
- Reason only from the evidence you are given; quote the numbers you rely on.
- Prefer hypotheses that make different, falsifiable predictions, and design experiments that could prove you wrong.
- Consider competing explanations (database, CPU, I/O, locking/synchronization, connection pools, the event loop, \
the workload itself) instead of anchoring on the first one that fits.
- You never decide whether a fix worked. HotPath runs the tests and benchmarks and decides that deterministically.
- Correctness is a hard constraint. A faster service that returns wrong results is a failed fix.

Respond with a single JSON object that matches the requested schema, and nothing else."""

INSTRUMENTS = """Instruments HotPath can run for an experiment (client latency and throughput are always measured):
- app_spans: in-process timing spans exported by the service (p50/p99 per span name)
- container_resources: average CPU % and peak memory of each container (app, db)
- db_activity: from PostgreSQL itself: active client connections (avg/max), idle-in-transaction connections, \
open connections, transactions per second (all committed transactions, including driver housekeeping such as connection resets), and the wait events of active connections
An experiment runs the service's real load test at 1 to 4 concurrency levels (between 1 and 1000 concurrent users).
Experiments are observational: they measure the CURRENT, unmodified code. Nothing can be changed, removed or patched \
during an experiment; fixes are only tested later, in a separate race."""

FORM_HYPOTHESES = """{context}

{instruments}

Task: propose up to {limit} competing hypotheses for why the objective is violated, ranked by your confidence.
- Each hypothesis must explain the evidence above and must be testable with ONE experiment using the instruments.
- Each experiment must include concrete predictions: what a specific measurement OF THE CURRENT CODE shows if the \
hypothesis is true, and what it shows if it is false. Never predict what the service would do after a fix.
- If earlier hypotheses were disproved, do not repeat them; use what their experiments revealed.
- Confidence is your honest prior probability (0 to 1) given the evidence so far.

Return JSON: {{"hypotheses": [Hypothesis, ...]}}"""

CONCLUDE = """{context}

## Hypothesis under test: {hypothesis_id}: {title}
{explanation}

## Experiment
Rationale: {rationale}
Predictions:
{predictions}

## Measured results
{results}

Task: compare each prediction with what was measured and decide whether the hypothesis is supported, disproved, \
or the experiment was inconclusive. Put the decisive measured facts, with numbers, in key_observations. \
Use high confidence only when the measurements clearly discriminate.
A measurement that falls between the two predicted outcomes does not refute the hypothesis: decide which prediction it \
is closer to (compare latencies by ratio, not difference), or call the result inconclusive. Disprove a hypothesis \
only when the measurements match what you predicted if it were false.
Before counting a measurement against the hypothesis, ask whether the hypothesis itself would cause it: a saturated \
pool, a busy database or slow queries can be consequences of the cause under test, not evidence against it. If a \
prediction was wrong only because it ignored such a consequence, discount that prediction rather than the hypothesis.
The experiment measured the unmodified code; nothing was changed. If a prediction describes the service after a fix, \
it cannot be tested this way: judge the hypothesis from what the measurements reveal about the current code instead, \
and never describe a change as having been made.

Return JSON matching ExperimentConclusion with hypothesis_id "{hypothesis_id}"."""

GENERATE_CANDIDATES = """{context}

## Supported root cause: {title}
{explanation}
Decisive observations:
{observations}

## Correctness tests that every fix must pass
{tests}

## Files you must not modify
{protected}
{previous}
Task: write {count} MATERIALLY DIFFERENT fixes for this root cause. They must use different strategies, \
not small variations of one idea. Each fix must:
- address the root cause above, keep the API and behaviour identical, and preserve correctness under concurrency;
- be a change to the code shown above: keep its existing function signatures, imports, names, tables and columns \
unless the fix itself changes them, and change only the files the fix needs;
- give the COMPLETE new contents of every file it changes (no diffs, no ellipses, no placeholders);
- only change application source (not tests, load tests, build or deployment files).
State honestly in `risks` what could go wrong with each approach.

Return JSON: {{"candidates": [{{"name", "strategy", "expected_effect", "risks", "changes": [{{"path", "content"}}]}}]}}"""
