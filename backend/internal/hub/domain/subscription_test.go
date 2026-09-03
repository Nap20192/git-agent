package domain

import "testing"

func strp(s string) *string { return &s }

func TestSubscriptionMatches(t *testing.T) {
	for name, tc := range map[string]struct {
		sub    BuildSubscription
		action string
		ref    string
		want   bool
	}{
		"empty actions = все действия":  {BuildSubscription{}, "push", "refs/heads/main", true},
		"action совпал":                 {BuildSubscription{Actions: []string{"push", "tag_push"}}, "push", "", true},
		"action не совпал":              {BuildSubscription{Actions: []string{"merge_request"}}, "push", "", false},
		"nil маска = любой ref":         {BuildSubscription{}, "push", "refs/heads/whatever", true},
		"маска release/* совпала":       {BuildSubscription{RefMask: strp("release/*")}, "push", "refs/heads/release/1.2", true},
		"маска release/* мимо":          {BuildSubscription{RefMask: strp("release/*")}, "push", "refs/heads/main", false},
		"маска по тегу":                 {BuildSubscription{RefMask: strp("v*")}, "tag_push", "refs/tags/v1.0", true},
		"маска без префикса refs":       {BuildSubscription{RefMask: strp("main")}, "push", "main", true},
		"бескоммитное событие с маской": {BuildSubscription{RefMask: strp("main")}, "issues", "", false},
		"битая маска не совпадает":      {BuildSubscription{RefMask: strp("[")}, "push", "refs/heads/main", false},
		"action и маска вместе": {
			BuildSubscription{Actions: []string{"push"}, RefMask: strp("release/*")},
			"push", "refs/heads/release/2.0", true,
		},
		"action совпал, маска нет": {
			BuildSubscription{Actions: []string{"push"}, RefMask: strp("release/*")},
			"push", "refs/heads/main", false,
		},
	} {
		if got := tc.sub.Matches(tc.action, tc.ref); got != tc.want {
			t.Errorf("%s: got %v, want %v", name, got, tc.want)
		}
	}
}

func TestMatchedBuilds(t *testing.T) {
	subs := []BuildSubscription{
		{BuildID: 1, Actions: []string{"push"}},
		{BuildID: 2, Actions: []string{"merge_request"}},
		{BuildID: 3}, // на всё
		{BuildID: 1}, // дубль Сборки — не должен задвоить
	}
	got := MatchedBuilds(subs, "push", "refs/heads/main")
	if len(got) != 2 || got[0] != 1 || got[1] != 3 {
		t.Errorf("got %v, want [1 3]", got)
	}
	if got := MatchedBuilds(nil, "push", ""); got != nil {
		t.Errorf("no subs: got %v", got)
	}
}

func TestShortRef(t *testing.T) {
	for in, want := range map[string]string{
		"refs/heads/main":        "main",
		"refs/heads/release/1.2": "release/1.2",
		"refs/tags/v1":           "v1",
		"main":                   "main",
		"":                       "",
	} {
		if got := ShortRef(in); got != want {
			t.Errorf("ShortRef(%q) = %q, want %q", in, got, want)
		}
	}
}
