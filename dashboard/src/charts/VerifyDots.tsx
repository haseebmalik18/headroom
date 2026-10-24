import type { Distribution } from "../data/types";
import { formatMs, formatTick, valueScale } from "./scale";
import { useSize } from "./useSize";

interface Props {
  baseline: Distribution | null;
  patched: Distribution;
  target: number;
}

const ROW = 56;
const PAD = { left: 84, right: 24, top: 28, bottom: 28 };

/** Every verification run as a dot, per series, with the 95% CI of the median shaded and the target line. */
export function VerifyDots({ baseline, patched, target }: Props) {
  const [ref, { width }] = useSize<HTMLDivElement>();
  const series = [
    ...(baseline ? [{ name: "before", d: baseline, color: "var(--slow)" }] : []),
    { name: "with the fix", d: patched, color: "var(--fast)" },
  ];
  const all = series.flatMap((s) => s.d.values).concat(target);
  const { scale, ticks, log } = valueScale(all, [PAD.left, Math.max(width - PAD.right, PAD.left + 50)]);
  const height = PAD.top + series.length * ROW + PAD.bottom;

  return (
    <figure className="verify-dots" ref={ref}>
      <figcaption>
        p99 of each repeated run · shaded: 95% CI of the median{log && <span className="muted"> · log scale</span>}
      </figcaption>
      <svg width={width} height={height} role="img"
           aria-label={series.map((s) => `${s.name} median ${formatMs(s.d.median)}`).join(", ")}>
        {ticks.map((t) => (
          <g key={t} className="axis">
            <line x1={scale(t)} x2={scale(t)} y1={PAD.top - 8} y2={height - PAD.bottom} />
            <text x={scale(t)} y={height - PAD.bottom + 18} textAnchor="middle">{formatTick(t)}</text>
          </g>
        ))}
        <g className="target">
          <line x1={scale(target)} x2={scale(target)} y1={PAD.top - 14} y2={height - PAD.bottom} />
          <text x={scale(target) + 6} y={PAD.top - 16}>target {formatTick(target)} ms</text>
        </g>
        {series.map((s, i) => {
          const y = PAD.top + i * ROW + ROW / 2;
          return (
            <g key={s.name}>
              <text className="series-label" x={0} y={y + 4}>{s.name}</text>
              <rect x={scale(s.d.ci_low)} width={Math.max(scale(s.d.ci_high) - scale(s.d.ci_low), 3)}
                    y={y - 14} height={28} rx={4} fill={s.color} opacity={0.14} />
              <line className="median" x1={scale(s.d.median)} x2={scale(s.d.median)} y1={y - 16} y2={y + 16}
                    stroke={s.color} />
              {s.d.values.map((v, j) => (
                <circle key={j} cx={scale(v)} cy={y + ((j % 3) - 1) * 5} r={5} fill={s.color} className="dot">
                  <title>{`${s.name} run ${j + 1}: ${formatMs(v)}`}</title>
                </circle>
              ))}
              <text className="series-value" x={Math.min(scale(s.d.ci_high) + 10, width - 4)} y={y - 18}
                    textAnchor={scale(s.d.ci_high) + 120 > width ? "end" : "start"}>
                median {formatMs(s.d.median)}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="legend">
        {series.map((s) => (
          <span key={s.name}><i style={{ background: s.color }} />{s.name} ({s.d.n} runs)</span>
        ))}
      </div>
    </figure>
  );
}
