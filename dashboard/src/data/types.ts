// Shapes written by `headroom export` (headroom/export.py). Event payloads mirror Headroom's pydantic models.

export interface Objective {
  endpoint: string;
  metric: string;
  target: number;
}

export interface RunEvent {
  at: string;
  phase: string;
  kind: string;
  message: string;
  data: Record<string, any>;
}

export interface Prediction {
  observation: string;
  if_supported: string;
  if_refuted: string;
}

export interface ExperimentPlan {
  rationale: string;
  concurrency_levels: number[];
  measurements: string[];
  predictions: Prediction[];
}

export interface Hypothesis {
  id: string;
  title: string;
  explanation: string;
  confidence: number;
  supporting_evidence: string[];
  contradicting_evidence: string[];
  missing_evidence: string[];
  proposed_experiment: ExperimentPlan;
}

export interface SpanSummary {
  p50_ms: number;
  p99_ms: number;
}

export interface DbActivity {
  samples: number;
  active_connections_avg: number;
  active_connections_max: number;
  idle_in_transaction_avg: number;
  pool_connections_max: number;
  commits_per_s: number | null;
  wait_events: Record<string, number>;
}

export interface LevelObservation {
  concurrency: number;
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
  throughput_rps: number;
  error_rate: number;
  container_cpu_percent: Record<string, number> | null;
  container_memory_mb: Record<string, number> | null;
  spans: Record<string, SpanSummary> | null;
  db: DbActivity | null;
}

export interface ExperimentResult {
  plan: ExperimentPlan;
  levels: LevelObservation[];
  error: string | null;
}

export interface Conclusion {
  hypothesis_id: string;
  verdict: "supported" | "disproved" | "inconclusive";
  confidence: number;
  key_observations: string[];
  explanation: string;
}

export type CandidateStatus = "winner" | "valid" | "rejected";

export interface Candidate {
  round: number;
  name: string;
  strategy: string;
  expected_effect: string;
  risks: string;
  changed_files: string[];
  diff: string;
  status: CandidateStatus;
  reasons: string[];
  failing_tests: string[];
  p99_ms: number | null;
  throughput_rps: number | null;
  tests_passed: number | null;
  tests_total: number | null;
  meets_slo: boolean;
}

export interface Distribution {
  n: number;
  values: number[];
  median: number;
  mean: number;
  stdev: number;
  ci_low: number;
  ci_high: number;
  confidence: number;
}

export interface RunStatistics {
  label: string;
  runs: number;
  tests_passed: number | null;
  tests_total: number | null;
  metric: Distribution;
  throughput_rps: Distribution;
  error_rate_max: number;
  memory_mb_max: number | null;
  slo_met_runs: number;
}

export interface Verification {
  objective: Objective;
  baseline: RunStatistics | null;
  candidate: RunStatistics;
  slo_recovered: boolean;
  error: string | null;
}

export type Phase = "awaiting_approval" | "slo_already_met" | "unresolved" | string;

export interface Run {
  id: string;
  recorded_at: string | null;
  service: string;
  scenario: string | null;
  model: string | null;
  actions_url: string | null;
  objective: Objective | null;
  baseline_ms: number | null;
  final_ms: number | null;
  events: RunEvent[];
  candidates: Candidate[];
  outcome: {
    phase: Phase;
    winner: string | null;
    diff: string | null;
    reason: string | null;
    verification: Verification | null;
  };
  usage: {
    calls: { task: string; latency_s: number; prompt_tokens: number; completion_tokens: number }[];
    total_tokens: number;
  };
}

export interface RunSummary {
  id: string;
  title: string;
  scenario: string | null;
  service: string;
  endpoint: string | null;
  phase: Phase;
  winner: string | null;
  baseline_ms: number | null;
  final_ms: number | null;
  recorded_at: string | null;
  actions_url: string | null;
}

export interface RunIndex {
  featured: string | null;
  runs: RunSummary[];
}
