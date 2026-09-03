// Package dnsfix — обход сломанного системного резолвера на dev-машине:
// при заданном DNS_SERVER (host[:port]) глобальный резолвер Go ходит в него
// напрямую (pure-Go), минуя stub systemd-resolved. Пусто = поведение по умолчанию.
package dnsfix

import (
	"context"
	"net"
	"time"
)

// Install — подменить net.DefaultResolver; server пустой — ничего не делает.
func Install(server string) {
	if server == "" {
		return
	}
	if _, _, err := net.SplitHostPort(server); err != nil {
		server = net.JoinHostPort(server, "53")
	}
	d := &net.Dialer{Timeout: 5 * time.Second}
	net.DefaultResolver = &net.Resolver{
		PreferGo: true,
		Dial: func(ctx context.Context, network, _ string) (net.Conn, error) {
			return d.DialContext(ctx, network, server)
		},
	}
}
