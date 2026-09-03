package httpapi

import (
	"encoding/json"
	"net/http/httptest"
	"testing"
)

func TestBuildInputValidateLimits(t *testing.T) {
	cases := []struct {
		name   string
		limits string
		ok     bool
	}{
		{"no limits", "", true},
		{"null limits", "null", true},
		{"empty object", "{}", true},
		{"valid known keys", `{"maxSubagents":2,"maxTotalSubagents":5,"subagentTimeout":900,"queueTimeout":60,"tokenBudget":500000}`, true},
		{"unknown keys pass through", `{"futureKnob":"whatever"}`, true},
		{"zero", `{"maxSubagents":0}`, false},
		{"negative", `{"tokenBudget":-1}`, false},
		{"non-numeric", `{"subagentTimeout":"600"}`, false},
		{"not an object", `[1,2]`, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			in := buildInput{Name: "b", LlmConnectionID: 1, SandboxConnectionID: 1, Limits: json.RawMessage(tc.limits)}
			w := httptest.NewRecorder()
			if got := in.validate(w); got != tc.ok {
				t.Fatalf("validate = %v, want %v (body: %s)", got, tc.ok, w.Body.String())
			}
			if !tc.ok && w.Code != 400 {
				t.Fatalf("status = %d, want 400", w.Code)
			}
		})
	}
}
