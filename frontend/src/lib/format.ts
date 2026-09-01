/** Small formatting helpers shared across screens. */

export function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/** Seconds -> "mm:ss". */
export function elapsed(sec: number): string {
  return `${pad2(Math.floor(sec / 60))}:${pad2(sec % 60)}`;
}

/** Token count -> "184k". */
export function tokensLabel(tokens: number): string {
  return `${Math.round(tokens / 1000)}k`;
}

/** Build an svg polyline points string scaled into a wxh box. */
export function sparkPoints(values: number[], w = 64, h = 22): string {
  if (values.length === 0) return "";
  const max = Math.max(...values);
  const min = Math.min(...values);
  const span = max - min || 1;
  const pad = 1;
  return values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * w;
      const y = h - pad - ((v - min) / span) * (h - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}
