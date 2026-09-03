package httpapi

import (
	"net/http"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
	"github.com/vnkjd/git-agent/backend/pkg/secrets"
)

// SandboxInstancesHandler — Экземпляры Сэндбоксов: создаёт/убивает их hub по
// команде юзера (раннер только подключается по external_id). Скоуп — как у
// sandbox-подключений: глобальный (в схеме нет user_id).
type SandboxInstancesHandler struct {
	Store       domain.SandboxInstanceStore
	Connections domain.ConnectionStore
	Sandboxes   domain.SandboxLifecycle
	Secrets     *secrets.Box
}

// List — GET /api/sandbox-instances.
func (h *SandboxInstancesHandler) List(w http.ResponseWriter, r *http.Request) {
	list, err := h.Store.SandboxInstances(r.Context())
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, mapSlice(list, toSandboxInstanceDTO))
}

// Create — POST /api/sandbox-instances {sandboxConnectionId}: OpenSandbox
// create (no-TTL) по координатам подключения + строка hub.sandbox_instances.
func (h *SandboxInstancesHandler) Create(w http.ResponseWriter, r *http.Request) {
	var req struct {
		SandboxConnectionID int64 `json:"sandboxConnectionId"`
	}
	if !decodeBody(w, r, &req) {
		return
	}
	conn, err := h.Connections.SandboxConnection(r.Context(), req.SandboxConnectionID)
	if err != nil {
		writeError(w, err)
		return
	}
	if conn == nil {
		writeError(w, domain.ErrNotFound)
		return
	}
	if conn.Image == nil || *conn.Image == "" {
		http.Error(w, `{"error":"sandbox connection has no image configured"}`, http.StatusBadRequest)
		return
	}
	apiKey := ""
	if conn.APIKeyEnc != nil {
		key, err := h.Secrets.Decrypt(conn.APIKeyEnc)
		if err != nil {
			writeError(w, err)
			return
		}
		apiKey = string(key)
	}
	externalID, err := h.Sandboxes.CreateSandbox(r.Context(), conn.Domain, apiKey, *conn.Image)
	if err != nil {
		writeError(w, err)
		return
	}
	id, err := h.Store.CreateSandboxInstance(r.Context(), externalID, conn.ID)
	if err != nil {
		writeError(w, err)
		return
	}
	si, err := h.Store.SandboxInstance(r.Context(), id)
	if err != nil || si == nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, toSandboxInstanceDTO(*si))
}

// Kill — DELETE /api/sandbox-instances/{id}: destroy у OpenSandbox + status=dead.
// Идемпотентно: уже dead — 204 без похода в OpenSandbox.
func (h *SandboxInstancesHandler) Kill(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	si, err := h.Store.SandboxInstance(r.Context(), id)
	if err != nil {
		writeError(w, err)
		return
	}
	if si == nil {
		writeError(w, domain.ErrNotFound)
		return
	}
	if si.Status != "dead" {
		conn, err := h.Connections.SandboxConnection(r.Context(), si.SandboxConnectionID)
		if err != nil {
			writeError(w, err)
			return
		}
		apiKey := ""
		if conn != nil && conn.APIKeyEnc != nil {
			if key, err := h.Secrets.Decrypt(conn.APIKeyEnc); err == nil {
				apiKey = string(key)
			}
		}
		domainAddr := ""
		if conn != nil {
			domainAddr = conn.Domain
		}
		if err := h.Sandboxes.DeleteSandbox(r.Context(), domainAddr, apiKey, si.ExternalID); err != nil {
			writeError(w, err)
			return
		}
		if err := h.Store.MarkSandboxInstanceDead(r.Context(), id); err != nil {
			writeError(w, err)
			return
		}
	}
	w.WriteHeader(http.StatusNoContent)
}

// Link — POST /api/instances/{id}/sandbox {sandboxInstanceId}: привязать
// Экземпляр Агента юзера к Экземпляру Сэндбокса.
func (h *SandboxInstancesHandler) Link(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	var req struct {
		SandboxInstanceID int64 `json:"sandboxInstanceId"`
	}
	if !decodeBody(w, r, &req) {
		return
	}
	if err := h.Store.LinkInstanceSandbox(r.Context(), id, req.SandboxInstanceID, userID(r)); err != nil {
		writeError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
