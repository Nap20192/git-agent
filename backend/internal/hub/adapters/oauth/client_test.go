package oauth

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
)

// GitHub App с истекающими токенами: refresh идёт на /login/oauth/access_token с grant_type=refresh_token.
func TestRefreshGitHub(t *testing.T) {
	var gotPath, gotGrant, gotRefresh string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = r.ParseForm()
		gotPath, gotGrant, gotRefresh = r.URL.Path, r.Form.Get("grant_type"), r.Form.Get("refresh_token")
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"access_token":"ghu_new","refresh_token":"ghr_new","expires_in":28800}`))
	}))
	defer srv.Close()

	c := &Client{GitHub: App{ClientID: "id", ClientSecret: "secret"}, GitHubWeb: srv.URL}
	tok, err := c.Refresh(context.Background(), "github", "ghr_old")
	if err != nil {
		t.Fatal(err)
	}
	if gotPath != "/login/oauth/access_token" || gotGrant != "refresh_token" || gotRefresh != "ghr_old" {
		t.Fatalf("request: path=%q grant=%q refresh=%q", gotPath, gotGrant, gotRefresh)
	}
	if tok.AccessToken != "ghu_new" || tok.RefreshToken != "ghr_new" || tok.ExpiresAt == nil {
		t.Fatalf("token: %+v", tok)
	}
}
