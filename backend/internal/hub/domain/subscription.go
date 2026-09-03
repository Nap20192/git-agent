package domain

import (
	"path"
	"time"
)

// BuildSubscription — подписка Сборки на события Репозитория (тикет 011):
// пустой actions = все действия, nil ref_mask = любой ref.
type BuildSubscription struct {
	ID           int64
	BuildID      int64
	RepositoryID int64
	Actions      []string
	RefMask      *string
	CreatedAt    time.Time
}

// Matches — совпадает ли подписка с Событием.
// ref сравнивается без префикса refs/heads|tags/, маска — glob (path.Match:
// "release/*"); битая маска не совпадает никогда.
func (s BuildSubscription) Matches(action, ref string) bool {
	if len(s.Actions) > 0 && !contains(s.Actions, action) {
		return false
	}
	if s.RefMask == nil {
		return true
	}
	if ref == "" {
		return false // бескоммитное событие под маску ветки не подпадает
	}
	ok, err := path.Match(*s.RefMask, ShortRef(ref))
	return err == nil && ok
}

// MatchedBuilds — id Сборок, чьи подписки совпали с Событием (без дублей).
func MatchedBuilds(subs []BuildSubscription, action, ref string) []int64 {
	var out []int64
	seen := map[int64]bool{}
	for _, s := range subs {
		if !seen[s.BuildID] && s.Matches(action, ref) {
			seen[s.BuildID] = true
			out = append(out, s.BuildID)
		}
	}
	return out
}

// ShortRef — "refs/heads/main" → "main", "refs/tags/v1" → "v1"; прочее как есть.
func ShortRef(ref string) string {
	for _, p := range []string{"refs/heads/", "refs/tags/"} {
		if len(ref) > len(p) && ref[:len(p)] == p {
			return ref[len(p):]
		}
	}
	return ref
}

func contains(list []string, v string) bool {
	for _, s := range list {
		if s == v {
			return true
		}
	}
	return false
}
