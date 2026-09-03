package httpapi

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/vnkjd/git-agent/backend/internal/hub/adapters/oauth"
	pgstore "github.com/vnkjd/git-agent/backend/internal/hub/adapters/postgres"
	"github.com/vnkjd/git-agent/backend/internal/hub/app"
	"github.com/vnkjd/git-agent/backend/internal/pkg/testdb"
	"github.com/vnkjd/git-agent/backend/pkg/secrets"
)

// authRig — hub с auth-роутами и защищённым /api/me против фейкового GitHub.
type authRig struct {
	srv       *httptest.Server
	db        *pgxpool.Pool
	box       *secrets.Box
	userID    atomic.Int64 // id пользователя, которого отдаёт фейковый провайдер
	username  atomic.Value
	lastToken atomic.Value // access_token, который выдал token-endpoint
}

func newAuthRig(t *testing.T) *authRig {
	t.Helper()
	rig := &authRig{db: testdb.Setup(t)}
	rig.box, _ = secrets.New(bytes.Repeat([]byte{4}, 32))
	rig.userID.Store(501)
	rig.username.Store("alice")

	fakeGitHub := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/login/oauth/access_token":
			tok := fmt.Sprintf("tok-%d", rig.userID.Load())
			rig.lastToken.Store(tok)
			fmt.Fprintf(w, `{"access_token":%q}`, tok)
		case "/user":
			fmt.Fprintf(w, `{"id":%d,"login":%q}`, rig.userID.Load(), rig.username.Load())
		default:
			t.Errorf("unexpected oauth call: %s", r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	t.Cleanup(fakeGitHub.Close)

	store := &pgstore.Store{Pool: rig.db}
	oauthClient := &oauth.Client{
		GitHub:    oauth.App{ClientID: "cid", ClientSecret: "csec"},
		GitHubWeb: fakeGitHub.URL, GitHubAPI: fakeGitHub.URL,
	}
	session := &Session{Store: store}
	auth := &AuthHandler{
		Service: &app.AuthService{Store: store, OAuth: oauthClient, Secrets: rig.box},
		Session: session, Store: store, Identities: store,
		FrontendURL: "http://front.example/",
	}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/auth/{provider}/login", auth.Login)
	mux.HandleFunc("GET /api/auth/{provider}/callback", auth.Callback)
	mux.HandleFunc("POST /api/auth/logout", auth.Logout)
	mux.HandleFunc("GET /api/me", session.Wrap(auth.Me))
	rig.srv = httptest.NewServer(mux)
	t.Cleanup(rig.srv.Close)
	return rig
}

// login — полный флоу login→callback; возвращает session cookie.
func (rig *authRig) login(t *testing.T, existingSession *http.Cookie) *http.Cookie {
	t.Helper()
	noRedirect := &http.Client{CheckRedirect: func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	}}

	resp, err := noRedirect.Get(rig.srv.URL + "/api/auth/github/login")
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != 302 {
		t.Fatalf("login status: %d", resp.StatusCode)
	}
	loc := resp.Header.Get("Location")
	if !strings.Contains(loc, "client_id=cid") || !strings.Contains(loc, "state=") {
		t.Fatalf("auth url: %s", loc)
	}
	var stateC *http.Cookie
	for _, c := range resp.Cookies() {
		if c.Name == stateCookie {
			stateC = c
		}
	}
	if stateC == nil {
		t.Fatal("no state cookie")
	}
	state := stateC.Value

	req, _ := http.NewRequest("GET", rig.srv.URL+"/api/auth/github/callback?code=c&state="+state, nil)
	req.AddCookie(stateC)
	if existingSession != nil {
		req.AddCookie(existingSession)
	}
	resp, err = noRedirect.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != 302 || resp.Header.Get("Location") != "http://front.example/" {
		t.Fatalf("callback: status=%d loc=%s", resp.StatusCode, resp.Header.Get("Location"))
	}
	for _, c := range resp.Cookies() {
		if c.Name == sessionCookie && c.Value != "" {
			if !c.HttpOnly {
				t.Error("session cookie is not httpOnly")
			}
			return c
		}
	}
	t.Fatal("no session cookie after callback")
	return nil
}

func (rig *authRig) count(t *testing.T, query string) int {
	t.Helper()
	var n int
	if err := rig.db.QueryRow(context.Background(), query).Scan(&n); err != nil {
		t.Fatal(err)
	}
	return n
}

// Вход → пользователь+связка одним флоу, токен в БД шифром; повторный вход —
// тот же пользователь; живая сессия + callback другого аккаунта — добавление связки.
func TestOAuthCallbackFlow(t *testing.T) {
	rig := newAuthRig(t)

	sess := rig.login(t, nil)
	if n := rig.count(t, `SELECT count(*) FROM hub.users`); n != 1 {
		t.Fatalf("users after first login: %d", n)
	}
	if n := rig.count(t, `SELECT count(*) FROM hub.identities`); n != 1 {
		t.Fatalf("identities: %d", n)
	}

	// токен хранится шифром и расшифровывается в выданный провайдером
	var enc []byte
	if err := rig.db.QueryRow(context.Background(),
		`SELECT access_token_enc FROM hub.identities`).Scan(&enc); err != nil {
		t.Fatal(err)
	}
	dec, err := rig.box.Decrypt(enc)
	if err != nil || string(dec) != rig.lastToken.Load().(string) {
		t.Fatalf("stored token: %q err=%v", dec, err)
	}

	// /api/me живой и не светит токены
	req, _ := http.NewRequest("GET", rig.srv.URL+"/api/me", nil)
	req.AddCookie(sess)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	body, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if resp.StatusCode != 200 || !bytes.Contains(body, []byte(`"alice"`)) {
		t.Fatalf("me: %d %s", resp.StatusCode, body)
	}
	if bytes.Contains(body, []byte("tok-")) {
		t.Fatal("access token leaked in /api/me")
	}

	// повторный вход тем же аккаунтом провайдера — тот же пользователь
	rig.login(t, nil)
	if n := rig.count(t, `SELECT count(*) FROM hub.users`); n != 1 {
		t.Fatalf("users after re-login: %d", n)
	}

	// живая сессия + вход другим аккаунтом = вторая связка того же пользователя
	rig.userID.Store(502)
	rig.username.Store("alice-work")
	rig.login(t, sess)
	if n := rig.count(t, `SELECT count(*) FROM hub.users`); n != 1 {
		t.Fatalf("users after attach: %d", n)
	}
	if n := rig.count(t, `SELECT count(*) FROM hub.identities`); n != 2 {
		t.Fatalf("identities after attach: %d", n)
	}
}

func TestOAuthStateMismatch(t *testing.T) {
	rig := newAuthRig(t)
	req, _ := http.NewRequest("GET", rig.srv.URL+"/api/auth/github/callback?code=c&state=forged", nil)
	req.AddCookie(&http.Cookie{Name: stateCookie, Value: "genuine"})
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != 400 {
		t.Fatalf("forged state: %d", resp.StatusCode)
	}
}

// Провайдер без ключей — 503 с понятным текстом, сервис живёт.
func TestOAuthUnconfiguredProvider(t *testing.T) {
	rig := newAuthRig(t) // gitlab-ключи не заданы
	resp, err := http.Get(rig.srv.URL + "/api/auth/gitlab/login")
	if err != nil {
		t.Fatal(err)
	}
	body, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if resp.StatusCode != 503 || !bytes.Contains(body, []byte("not configured")) {
		t.Fatalf("unconfigured: %d %s", resp.StatusCode, body)
	}
}

// Middleware: без cookie — 401; истёкшая сессия — 401; после logout — 401.
func TestSessionMiddleware(t *testing.T) {
	rig := newAuthRig(t)

	resp, _ := http.Get(rig.srv.URL + "/api/me")
	resp.Body.Close()
	if resp.StatusCode != 401 {
		t.Fatalf("no cookie: %d", resp.StatusCode)
	}

	sess := rig.login(t, nil)
	req, _ := http.NewRequest("GET", rig.srv.URL+"/api/me", nil)
	req.AddCookie(sess)
	resp, _ = http.DefaultClient.Do(req)
	resp.Body.Close()
	if resp.StatusCode != 200 {
		t.Fatalf("valid session: %d", resp.StatusCode)
	}

	// истёкшая сессия
	if _, err := rig.db.Exec(context.Background(),
		`UPDATE hub.sessions SET expires_at = now() - interval '1 minute' WHERE token = $1`, sess.Value); err != nil {
		t.Fatal(err)
	}
	resp, _ = http.DefaultClient.Do(req)
	resp.Body.Close()
	if resp.StatusCode != 401 {
		t.Fatalf("expired session: %d", resp.StatusCode)
	}

	// logout уничтожает сессию
	sess2 := rig.login(t, nil)
	lo, _ := http.NewRequest("POST", rig.srv.URL+"/api/auth/logout", nil)
	lo.AddCookie(sess2)
	resp, _ = http.DefaultClient.Do(lo)
	resp.Body.Close()
	if resp.StatusCode != 204 {
		t.Fatalf("logout: %d", resp.StatusCode)
	}
	req2, _ := http.NewRequest("GET", rig.srv.URL+"/api/me", nil)
	req2.AddCookie(sess2)
	resp, _ = http.DefaultClient.Do(req2)
	resp.Body.Close()
	if resp.StatusCode != 401 {
		t.Fatalf("after logout: %d", resp.StatusCode)
	}
}
