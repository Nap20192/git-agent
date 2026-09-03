package app

import "testing"

func TestMaskKey(t *testing.T) {
	for in, want := range map[string]string{
		"":            "",
		"abc":         "…",
		"abcd":        "…",
		"sk-12345678": "…5678",
	} {
		if got := MaskKey(in); got != want {
			t.Errorf("MaskKey(%q) = %q, want %q", in, got, want)
		}
	}
}
