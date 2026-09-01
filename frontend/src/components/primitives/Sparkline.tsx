import { sparkPoints } from "@/lib/format.ts";
import { toneVar, type Tone } from "@/lib/tone.ts";

export interface SparklineProps {
  values: number[];
  tone?: Tone;
  width?: number;
  height?: number;
}

/** Tiny inline trend line for stat tiles. */
export function Sparkline({ values, tone = "muted", width = 64, height = 22 }: SparklineProps) {
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      style={{ width, height, flexShrink: 0 }}
    >
      <polyline
        points={sparkPoints(values, width, height)}
        fill="none"
        stroke={toneVar(tone)}
        strokeWidth={1.2}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
