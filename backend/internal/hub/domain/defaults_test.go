package domain

import (
	"encoding/json"
	"testing"
)

func TestFillLimits(t *testing.T) {
	parse := func(b []byte) map[string]any {
		var m map[string]any
		if err := json.Unmarshal(b, &m); err != nil {
			t.Fatalf("bad json %s: %v", b, err)
		}
		return m
	}
	for _, raw := range []string{"", "null", "{}"} {
		m := parse(FillLimits([]byte(raw)))
		if m["maxSubagents"] != float64(3) || m["queueTimeout"] != float64(300) || len(m) != len(DefaultLimits) {
			t.Fatalf("%q → %v", raw, m)
		}
	}
	m := parse(FillLimits([]byte(`{"maxSubagents":8,"futureKnob":"x"}`)))
	if m["maxSubagents"] != float64(8) || m["futureKnob"] != "x" || m["subagentTimeout"] != float64(600) {
		t.Fatalf("partial → %v", m)
	}
	if _, ok := m["tokenBudget"]; ok {
		t.Fatal("tokenBudget must stay unset")
	}
	if got := string(FillLimits([]byte(`[1]`))); got != `[1]` {
		t.Fatalf("non-object must pass through, got %s", got)
	}
}

func TestConnectionDefaults(t *testing.T) {
	d := Defaults{LlmAPIBase: "https://api.x/v1", LlmModel: "m", SandboxDomain: "localhost:8090", SandboxImage: "alpine/git:latest"}
	llm := LlmConnection{Model: "custom"}
	llm.ApplyDefaults(d)
	if llm.APIBase != d.LlmAPIBase || llm.Model != "custom" {
		t.Fatalf("llm: %+v", llm)
	}
	empty := ""
	sb := SandboxConnection{Image: &empty}
	sb.ApplyDefaults(d)
	if sb.Domain != d.SandboxDomain || sb.Image == nil || *sb.Image != d.SandboxImage {
		t.Fatalf("sandbox: %+v", sb)
	}
}
