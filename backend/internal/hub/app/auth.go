package app

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"log/slog"
	"time"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
	"github.com/vnkjd/git-agent/backend/pkg/secrets"
)

const SessionTTL = 30 * 24 * time.Hour

// AuthService — OAuth-вход по модели Railway (тикет 003): паролей нет,
// первый вход создаёт пользователя и связку одним флоу; живая сессия +
// callback = добавление ещё одной связки текущему пользователю.
type AuthService struct {
	Store   domain.AuthStore
	OAuth   domain.OAuthClient
	Secrets *secrets.Box
}

func randomToken() (string, error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

// LoginURL — redirect на провайдера; провайдер без ключей — ErrUnavailable.
func (s *AuthService) LoginURL(provider, redirectURI, state string) (string, error) {
	return s.OAuth.AuthURL(provider, redirectURI, state)
}

// HandleCallback — обмен кода на токен, профиль, upsert связки, сессия.
// currentUser != nil (живая сессия) — добавление связки; иначе вход.
func (s *AuthService) HandleCallback(ctx context.Context, provider, code, redirectURI string, currentUser *int64) (string, time.Time, error) {
	tok, err := s.OAuth.Exchange(ctx, provider, code, redirectURI)
	if err != nil {
		return "", time.Time{}, fmt.Errorf("exchange code: %w", err)
	}
	providerUserID, username, err := s.OAuth.UserInfo(ctx, provider, tok.AccessToken)
	if err != nil {
		return "", time.Time{}, fmt.Errorf("userinfo: %w", err)
	}
	accessEnc, refreshEnc, err := s.encryptTokens(tok)
	if err != nil {
		return "", time.Time{}, err
	}

	existing, err := s.Store.FindIdentityByProviderUser(ctx, provider, providerUserID)
	if err != nil {
		return "", time.Time{}, err
	}

	var userID int64
	switch {
	case currentUser != nil && existing != nil && existing.UserID != *currentUser:
		// связка уже принадлежит другому пользователю
		return "", time.Time{}, fmt.Errorf("identity belongs to another user: %w", domain.ErrConflict)
	case existing != nil:
		if err := s.Store.UpdateIdentityTokens(ctx, existing.ID, username, accessEnc, refreshEnc, tok.ExpiresAt); err != nil {
			return "", time.Time{}, err
		}
		userID = existing.UserID
	case currentUser != nil:
		userID = *currentUser
		if _, err := s.insertIdentity(ctx, userID, provider, providerUserID, username, accessEnc, refreshEnc, tok.ExpiresAt); err != nil {
			return "", time.Time{}, err
		}
	default:
		// первый вход: пользователь + связка одним флоу
		userID, err = s.Store.CreateUser(ctx, username)
		if err != nil {
			return "", time.Time{}, err
		}
		if _, err := s.insertIdentity(ctx, userID, provider, providerUserID, username, accessEnc, refreshEnc, tok.ExpiresAt); err != nil {
			return "", time.Time{}, err
		}
	}

	session, err := randomToken()
	if err != nil {
		return "", time.Time{}, err
	}
	expires := time.Now().Add(SessionTTL)
	if err := s.Store.CreateSession(ctx, session, userID, expires); err != nil {
		return "", time.Time{}, err
	}
	return session, expires, nil
}

func (s *AuthService) insertIdentity(ctx context.Context, userID int64, provider, providerUserID, username string, accessEnc, refreshEnc []byte, expiresAt *time.Time) (int64, error) {
	return s.Store.InsertIdentity(ctx, &domain.Identity{
		UserID: userID, Provider: provider, ProviderUserID: providerUserID, Username: username,
		AccessTokenEnc: accessEnc, RefreshTokenEnc: refreshEnc, TokenExpiresAt: expiresAt,
	})
}

func (s *AuthService) encryptTokens(tok *domain.OAuthToken) (accessEnc, refreshEnc []byte, err error) {
	accessEnc, err = s.Secrets.Encrypt([]byte(tok.AccessToken))
	if err != nil {
		return nil, nil, err
	}
	if tok.RefreshToken != "" {
		refreshEnc, err = s.Secrets.Encrypt([]byte(tok.RefreshToken))
		if err != nil {
			return nil, nil, err
		}
	}
	return accessEnc, refreshEnc, nil
}

func (s *AuthService) Logout(ctx context.Context, token string) error {
	return s.Store.DeleteSession(ctx, token)
}

// CallWithToken — вызов API провайдера токеном связки; на 401 от провайдера
// (ErrUnauthorized) — refresh-флоу (тикет 003: GitLab; у GitHub OAuth App
// токены вечные), новые токены персистятся, вызов повторяется один раз.
func (s *AuthService) CallWithToken(ctx context.Context, ident *domain.Identity, fn func(token string) error) error {
	token, err := s.Secrets.Decrypt(ident.AccessTokenEnc)
	if err != nil {
		return err
	}
	err = fn(string(token))
	if !errors.Is(err, domain.ErrUnauthorized) || ident.RefreshTokenEnc == nil {
		return err
	}

	refresh, decErr := s.Secrets.Decrypt(ident.RefreshTokenEnc)
	if decErr != nil {
		return err
	}
	tok, refErr := s.OAuth.Refresh(ctx, ident.Provider, string(refresh))
	if refErr != nil {
		slog.Warn("auth: token refresh failed", "identityId", ident.ID, "err", refErr)
		return err
	}
	accessEnc, refreshEnc, encErr := s.encryptTokens(tok)
	if encErr != nil {
		return encErr
	}
	if err := s.Store.UpdateIdentityTokens(ctx, ident.ID, ident.Username, accessEnc, refreshEnc, tok.ExpiresAt); err != nil {
		return err
	}
	ident.AccessTokenEnc = accessEnc
	ident.RefreshTokenEnc = refreshEnc
	return fn(tok.AccessToken)
}
