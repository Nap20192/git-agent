package domain

import (
	"encoding/json"
	"strings"
)

// Defaults — значения для пустых полей при создании: пустое поле заполняется
// здесь и сохраняется явно, а не остаётся NULL «на усмотрение раннера».
// Env-часть (LLM/OpenSandbox) читает cmd/hub/config из тех же ключей .env, что и агент.
type Defaults struct {
	LlmAPIBase    string // LLM_API_BASE
	LlmModel      string // LLM_MODEL
	SandboxDomain string // OPENSANDBOX_DOMAIN, дефолт localhost:8090
	SandboxAPIKey string // OPENSANDBOX_API_KEY
	SandboxImage  string // SANDBOX_IMAGE, дефолт git-agent/sandbox:strix
}

// DefaultLimits — зеркало дефолтов раннера (agent/core/lead/graph.py::_lead_features,
// SubagentCapacity, SubagentConfig). tokenBudget дефолта не имеет — бюджет выключен.
var DefaultLimits = map[string]any{
	"maxSubagents":      3,
	"maxTotalSubagents": 6,
	"subagentTimeout":   600,
	"queueTimeout":      300,
}

// FillLimits дописывает недостающие ключи DefaultLimits; заданные и незнакомые
// ключи не трогает. Пустое/null тело — полный набор дефолтов.
func FillLimits(raw []byte) []byte {
	m := map[string]any{}
	if s := strings.TrimSpace(string(raw)); s != "" && s != "null" {
		if err := json.Unmarshal(raw, &m); err != nil {
			return raw // не объект — валидация выше отдаст 400, здесь не наше дело
		}
	}
	for k, v := range DefaultLimits {
		if _, ok := m[k]; !ok {
			m[k] = v
		}
	}
	out, _ := json.Marshal(m)
	return out
}

func (b *AgentBuild) ApplyDefaults() {
	b.Limits = FillLimits(b.Limits)
}

func (c *LlmConnection) ApplyDefaults(d Defaults) {
	if c.APIBase == "" {
		c.APIBase = d.LlmAPIBase
	}
	if c.Model == "" {
		c.Model = d.LlmModel
	}
}

func (c *SandboxConnection) ApplyDefaults(d Defaults) {
	if c.Domain == "" {
		c.Domain = d.SandboxDomain
	}
	if (c.Image == nil || *c.Image == "") && d.SandboxImage != "" {
		img := d.SandboxImage
		c.Image = &img
	}
}
