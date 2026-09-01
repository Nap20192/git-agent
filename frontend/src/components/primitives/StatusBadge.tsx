import type { RunStatus } from "@/api";
import { runIcon, runLabel, runTone } from "@/lib/status.ts";
import { toneVar } from "@/lib/tone.ts";

/** Run status pill: icon + label in the status tone. */
export function StatusBadge({ status, withIcon = true }: { status: RunStatus; withIcon?: boolean }) {
  const color = toneVar(runTone(status));
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, color, fontSize: 11, whiteSpace: "nowrap" }}>
      {withIcon && <span style={{ fontSize: 10 }}>{runIcon(status)}</span>}
      {runLabel(status)}
    </span>
  );
}
