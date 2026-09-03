// Package testdb — Postgres для интеграционных тестов hub: отдельная БД
// git_agent_hub_test создаётся с нуля и мигрируется из 001_init.sql,
// рабочая БД не загрязняется (по образцу agent/tests/conftest.py).
package testdb

import (
	"context"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Setup возвращает пул на свежую мигрированную тестовую БД.
// Postgres недоступен → t.Skip: юнит-прогон без сервисов не падает.
func Setup(t *testing.T) *pgxpool.Pool {
	t.Helper()
	ctx := context.Background()
	// pid в имени: тестовые пакеты бегут параллельно в разных процессах
	testDB := fmt.Sprintf("git_agent_hub_test_%d", os.Getpid())

	base := os.Getenv("HUB_TEST_DATABASE_URL")
	if base == "" {
		base = "postgresql://git_agent:git_agent@localhost:5433/git_agent"
	}
	admin, err := pgx.Connect(ctx, base)
	if err != nil {
		t.Skipf("postgres unavailable: %v", err)
	}
	defer admin.Close(ctx)
	if _, err := admin.Exec(ctx, fmt.Sprintf("DROP DATABASE IF EXISTS %s WITH (FORCE)", testDB)); err != nil {
		t.Fatal(err)
	}
	if _, err := admin.Exec(ctx, "CREATE DATABASE "+testDB); err != nil {
		t.Fatal(err)
	}

	u, err := url.Parse(base)
	if err != nil {
		t.Fatal(err)
	}
	u.Path = "/" + testDB

	pool, err := pgxpool.New(ctx, u.String())
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		pool.Close()
		if c, err := pgx.Connect(context.Background(), base); err == nil {
			_, _ = c.Exec(context.Background(), "DROP DATABASE IF EXISTS "+testDB)
			c.Close(context.Background())
		}
	})

	_, self, _, _ := runtime.Caller(0)
	files, err := filepath.Glob(filepath.Join(filepath.Dir(self), "../../../../migrations/backend/*.sql"))
	if err != nil || len(files) == 0 {
		t.Fatalf("no backend migrations found: %v", err)
	}
	sort.Strings(files) // нумерованные SQL — применяются по порядку
	for _, f := range files {
		sql, err := os.ReadFile(f)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := pool.Exec(ctx, string(sql)); err != nil {
			t.Fatalf("apply %s: %v", filepath.Base(f), err)
		}
	}
	return pool
}
