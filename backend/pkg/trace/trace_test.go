package trace

import (
	"context"
	"testing"
)

func TestNewAccept(t *testing.T) {
	id := New()
	if !Valid(id) || id[12] != '4' {
		t.Fatalf("bad id %q", id)
	}
	if Accept("ABCDEF0123456789abcdef0123456789") != "abcdef0123456789abcdef0123456789" {
		t.Error("valid header must be accepted lowercased")
	}
	for _, bad := range []string{"", "short", "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz", "0123456789abcdef0123456789abcdef0"} {
		if got := Accept(bad); got == bad || !Valid(got) {
			t.Errorf("Accept(%q) = %q", bad, got)
		}
	}
	if FromContext(context.Background()) != "" || FromContext(WithValue(context.Background(), id)) != id {
		t.Error("ctx roundtrip")
	}
	if FromMessage([]byte(`{"eventId":1,"traceId":"`+id+`"}`)) != id || FromMessage([]byte(`{}`)) != "" {
		t.Error("FromMessage")
	}
}
