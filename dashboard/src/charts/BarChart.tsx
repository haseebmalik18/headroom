import { formatMs, formatTick, valueScale } from "./scale";

export type Tone = "neutral" | "good" | "critical" | "accent";

export interface Bar {
  label: string;
  value: number;
  tone?: Tone;
  hatched?: boolean; // secondary channel for "rejected", always paired with a text note
  note?: string;
}

interface Props {
  bars: Bar[];
  target?: number;
  caption?: string;
}

/** Horizontal bars on one latency axis (log when values span >10x), with an optional target line. */
export function BarChart({ bars, target, caption }: Props) {
  const values = bars.map((b) => b.value).concat(target ? [target] : []);
  const { scale, ticks, log } = valueScale(values, [0, 100]);
  return (
    <figure className="bars">
      {caption && <figcaption>{caption}{log && <span className="muted"> · log scale</span>}</figcaption>}
      <div className="bars-plot">
        <div className="bars-grid" aria-hidden>
          {ticks.map((t) => (
            <span key={t} style={{ left: `${scale(t)}%` }}><i>{formatTick(t)}</i></span>
          ))}
          {target !== undefined && (
            <span className="bars-target" style={{ left: `${scale(target)}%` }}><i>target {formatTick(target)}</i></span>
          )}
        </div>
        {bars.map((b) => (
          <div className="bar-row" key={b.label} title={`${b.label}: ${formatMs(b.value)}${b.note ? ` (${b.note})` : ""}`}>
            <div className="bar-label">{b.label}</div>
            <div className="bar-track">
              <div className={`bar tone-${b.tone ?? "neutral"}${b.hatched ? " hatched" : ""}`}
                   style={{ width: `${Math.max(scale(b.value), 0.8)}%` }} />
              <span className="bar-value">{formatMs(b.value)}{b.note && <em> · {b.note}</em>}</span>
            </div>
          </div>
        ))}
      </div>
    </figure>
  );
}
