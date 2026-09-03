package httpapi

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"strconv"

	"github.com/vnkjd/git-agent/backend/internal/hub/app"
	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

// InstancesHandler — Экземпляры Агентов: список/деталь/результаты + операции
// через Раннер (chat-прокси, stop).
type InstancesHandler struct {
	Store   domain.InstanceStore
	Service *app.InstanceService
}

// List — GET /api/instances[?repositoryId=].
func (h *InstancesHandler) List(w http.ResponseWriter, r *http.Request) {
	var repoID *int64
	if q := r.URL.Query().Get("repositoryId"); q != "" {
		id, err := strconv.ParseInt(q, 10, 64)
		if err != nil {
			badRequest(w, "repositoryId must be an integer")
			return
		}
		repoID = &id
	}
	list, err := h.Store.Instances(r.Context(), userID(r), repoID)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, mapSlice(list, toInstanceDTO))
}

// Get — GET /api/instances/{id}.
func (h *InstancesHandler) Get(w http.ResponseWriter, r *http.Request) {
	inst, ok := h.instance(w, r)
	if !ok {
		return
	}
	writeJSON(w, http.StatusOK, toInstanceDTO(*inst))
}

// Reports — GET /api/instances/{id}/reports.
func (h *InstancesHandler) Reports(w http.ResponseWriter, r *http.Request) {
	inst, ok := h.instance(w, r)
	if !ok {
		return
	}
	reports, err := h.Store.Reports(r.Context(), inst.ID)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, mapSlice(reports, func(rep domain.Report) reportDTO {
		return reportDTO(rep)
	}))
}

// Findings — GET /api/instances/{id}/findings.
func (h *InstancesHandler) Findings(w http.ResponseWriter, r *http.Request) {
	inst, ok := h.instance(w, r)
	if !ok {
		return
	}
	findings, err := h.Store.Findings(r.Context(), inst.ID)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, mapSlice(findings, func(f domain.Finding) findingDTO {
		return findingDTO(f)
	}))
}

// Activity — GET /api/instances/{id}/activity[?eventId=]: SSE activity-кадров
// хода (ActivityEvent, openapi.yaml). Running-Экземпляр — прокси в раннер;
// down — hub реплеит из hub.activity сам. Терминальный кадр — kind=done.
func (h *InstancesHandler) Activity(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	var eventID *int64
	if q := r.URL.Query().Get("eventId"); q != "" {
		v, err := strconv.ParseInt(q, 10, 64)
		if err != nil {
			badRequest(w, "eventId must be an integer")
			return
		}
		eventID = &v
	}
	stream, err := h.Service.Activity(r.Context(), id, userID(r), eventID)
	if err != nil {
		writeError(w, err)
		return
	}
	pipeSSE(w, stream, "activity", id)
}

// Stop — POST /api/instances/{id}/stop.
func (h *InstancesHandler) Stop(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	if err := h.Service.Stop(r.Context(), id, userID(r)); err != nil {
		writeError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// Raise — POST /api/instances/{id}/raise: явный подъём через Раннер.
// 200 {status: running} — поднят; 202 {status: queued} — слоты заняты,
// раннер поднимет фоном (202 раннера пробрасывается как есть).
func (h *InstancesHandler) Raise(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	queued, err := h.Service.Raise(r.Context(), id, userID(r))
	if err != nil {
		writeError(w, err)
		return
	}
	if queued {
		writeJSON(w, http.StatusAccepted, map[string]string{"status": "queued"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "running"})
}

// Resume — POST /api/instances/{id}/resume: «Продолжить» — незавершённые
// События Экземпляра снова в outbox; ответ — пере-опубликованные eventId
// (пустой список = нечего продолжать).
func (h *InstancesHandler) Resume(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	eventIDs, err := h.Service.Resume(r.Context(), id, userID(r))
	if err != nil {
		writeError(w, err)
		return
	}
	if eventIDs == nil {
		eventIDs = []int64{}
	}
	writeJSON(w, http.StatusOK, map[string][]int64{"eventIds": eventIDs})
}

// Chat — POST /api/instances/{id}/chat: SSE-прокси в Раннер (down-Экземпляр
// сначала поднимается). Кадры ChatEvent (openapi.yaml) идут от раннера как есть.
func (h *InstancesHandler) Chat(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	var req struct {
		Message string `json:"message"`
	}
	if !decodeBody(w, r, &req) {
		return
	}
	if req.Message == "" {
		badRequest(w, "message is required")
		return
	}
	stream, err := h.Service.Chat(r.Context(), id, userID(r), req.Message)
	if err != nil {
		writeError(w, err)
		return
	}
	pipeSSE(w, stream, "chat", id)
}

// Terminal — POST /api/instances/{id}/terminal: SSE-прокси стрим-консоли в
// Раннер. Кадры TerminalEvent (openapi.yaml) идут от раннера как есть;
// down-Экземпляр/отсутствующая песочница — 409, ничего не поднимается.
func (h *InstancesHandler) Terminal(w http.ResponseWriter, r *http.Request) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	var req struct {
		Command string `json:"command"`
	}
	if !decodeBody(w, r, &req) {
		return
	}
	if req.Command == "" {
		badRequest(w, "command is required")
		return
	}
	stream, err := h.Service.Terminal(r.Context(), id, userID(r), req.Command)
	if err != nil {
		writeError(w, err)
		return
	}
	pipeSSE(w, stream, "terminal", id)
}

// pipeSSE — прокинуть SSE-поток раннера клиенту как есть, с flush по-кадрово.
func pipeSSE(w http.ResponseWriter, stream io.ReadCloser, label string, id int64) {
	defer stream.Close()

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.WriteHeader(http.StatusOK)

	flusher, _ := w.(http.Flusher)
	buf := make([]byte, 4096)
	for {
		n, err := stream.Read(buf)
		if n > 0 {
			if _, werr := w.Write(buf[:n]); werr != nil {
				return // клиент отвалился
			}
			if flusher != nil {
				flusher.Flush()
			}
		}
		if err != nil {
			if err != io.EOF {
				// закрытая вкладка/переключение экрана — штатный обрыв SSE, не warning
				if errors.Is(err, context.Canceled) {
					slog.Info("instances: "+label+" stream closed by client", "instanceId", id)
				} else {
					slog.Warn("instances: "+label+" stream interrupted", "instanceId", id, "err", err)
				}
			}
			return
		}
	}
}

func (h *InstancesHandler) instance(w http.ResponseWriter, r *http.Request) (*domain.AgentInstance, bool) {
	id, ok := pathID(w, r)
	if !ok {
		return nil, false
	}
	inst, err := h.Store.Instance(r.Context(), id, userID(r))
	if err != nil {
		writeError(w, err)
		return nil, false
	}
	if inst == nil {
		writeError(w, domain.ErrNotFound)
		return nil, false
	}
	return inst, true
}
