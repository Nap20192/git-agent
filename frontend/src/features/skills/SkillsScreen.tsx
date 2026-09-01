/**
 * Capabilities & skills catalog. Honest framing: git-agent has no "skills"
 * concept in its backend today — this surfaces the REAL capabilities
 * (RuntimeFeatures flags + memory presets) alongside forward-looking agent
 * skills, each labelled active vs planned.
 */
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { Capability, CapabilitySource } from "@/api";
import { useCapabilities, useMemoryPresets } from "@/hooks";
import { Badge, Panel, Drawer, CodeBlock } from "@/components/primitives";
import type { Tone } from "@/lib/tone.ts";
import styles from "./SkillsScreen.module.css";

type Filter = "all" | CapabilitySource;

const SOURCE_TONE: Record<CapabilitySource, Tone> = {
  subagent: "amber",
  tool: "blue",
  capability: "low",
  memory_preset: "med",
};
const SOURCE_LABEL: Record<CapabilitySource, string> = {
  subagent: "sub-agent",
  tool: "tool",
  capability: "capability",
  memory_preset: "memory preset",
};

/** The example agent run every "used by" chip links to. */
const EXAMPLE_RUN = "/runs/run-1039";

export function SkillsScreen() {
  const navigate = useNavigate();
  const skillsQ = useCapabilities();
  const presetsQ = useMemoryPresets();
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<Capability | null>(null);

  const skills = skillsQ.data ?? [];
  const filtered = useMemo(
    () => (filter === "all" ? skills : skills.filter((s) => s.source === filter)),
    [skills, filter],
  );

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: skills.length };
    (["subagent", "tool", "capability", "memory_preset"] as CapabilitySource[]).forEach(
      (s) => (c[s] = skills.filter((k) => k.source === s).length),
    );
    return c;
  }, [skills]);

  const filters: Filter[] = ["all", "subagent", "tool", "capability", "memory_preset"];
  const presets = presetsQ.data ?? [];

  return (
    <div className={styles.screen}>
      <div className={styles.inner}>
        <div className={styles.head}>
          <h1 className={styles.title}>capabilities &amp; skills</h1>
          <span className={styles.path}>~/git-agent/skills</span>
        </div>

        <p className={styles.explainer}>
          git-agent has no "skills" concept — the honest, real capabilities are its{" "}
          <b>sub-agent types</b> (registry.py), the <b>sandbox toolset</b> (tools.py),{" "}
          <b>RuntimeFeatures</b> flags and <b>memory presets</b>. Each is labelled <b>active</b>{" "}
          (wired into the run/agent path now) or <b>planned</b> (not yet wired).
        </p>

        <div className={styles.filters}>
          {filters.map((f) => (
            <span
              key={f}
              className={[styles.filter, filter === f ? styles.filterOn : ""].join(" ")}
              onClick={() => setFilter(f)}
            >
              {f === "all" ? "all" : SOURCE_LABEL[f]} {counts[f] ?? 0}
            </span>
          ))}
        </div>

        {filtered.length === 0 ? (
          <div className={styles.empty}>{skillsQ.loading ? "loading…" : "no skills"}</div>
        ) : (
          <div className={styles.grid}>
            {filtered.map((s) => (
              <Panel key={s.id} className={styles.card} style={{ cursor: "pointer" }}>
                <div onClick={() => setSelected(s)} style={{ display: "contents" }}>
                  <div className={styles.cardHead}>
                    <span className={styles.name}>{s.name}</span>
                    <Badge tone={SOURCE_TONE[s.source]} uppercase>
                      {SOURCE_LABEL[s.source]}
                    </Badge>
                    <ActiveBadge active={s.active} />
                  </div>
                  <p className={styles.desc}>{s.description}</p>
                  {s.tags.length > 0 && (
                    <div className={styles.tags}>
                      {s.tags.map((t) => (
                        <span key={t} className={styles.tag}>
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </Panel>
            ))}
          </div>
        )}

        <div className={styles.presets}>
          <div className={styles.presetHead}>
            <h2 className={styles.presetTitle}>memory presets</h2>
            <span className={styles.presetNote}>real, named context-management presets (core/memory)</span>
          </div>
          {presets.length === 0 ? (
            <div className={styles.empty}>{presetsQ.loading ? "loading…" : "no presets"}</div>
          ) : (
            <div className={styles.presetList}>
              {presets.map((p) => (
                <Panel key={p.name} soft className={styles.presetCard}>
                  <div className={styles.presetName}>
                    {p.name}
                    {p.production && (
                      <Badge tone="low" uppercase>
                        prod
                      </Badge>
                    )}
                  </div>
                  <p className={styles.presetDesc}>{p.description}</p>
                </Panel>
              ))}
            </div>
          )}
        </div>
      </div>

      <Drawer
        open={selected != null}
        title={selected ? `◈ ${selected.name}` : ""}
        onClose={() => setSelected(null)}
        width={460}
      >
        {selected && (
          <>
            <div className={styles.drawerBadges}>
              <Badge tone={SOURCE_TONE[selected.source]} uppercase>
                {SOURCE_LABEL[selected.source]}
              </Badge>
              <ActiveBadge active={selected.active} />
            </div>
            <p className={styles.drawerDesc}>{selected.description}</p>

            <label className={styles.sectionLabel}>DETAIL</label>
            <CodeBlock accent={SOURCE_TONE[selected.source]} copyable={false}>
              {selected.body}
            </CodeBlock>

            {selected.usedBy.length > 0 && (
              <>
                <label className={styles.sectionLabel}>USED BY</label>
                <div className={styles.usedBy}>
                  {selected.usedBy.map((u) => (
                    <span key={u} className={styles.usedByChip} onClick={() => navigate(EXAMPLE_RUN)}>
                      {u} →
                    </span>
                  ))}
                </div>
              </>
            )}
          </>
        )}
      </Drawer>
    </div>
  );
}

function ActiveBadge({ active }: { active: boolean }) {
  return active ? (
    <Badge tone="low" uppercase>
      active
    </Badge>
  ) : (
    <Badge tone="med" uppercase>
      planned
    </Badge>
  );
}
