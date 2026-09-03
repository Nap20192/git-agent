package httpapi

import (
	"net/http"

	"github.com/vnkjd/git-agent/backend/internal/hub/domain"
)

// Операции над Экземпляром через Раннер.

// GET /api/instances/{id}/activity[?eventId=].
func (s *Server) instanceActivity(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	eventID, err := queryID(r, "eventId")
	if err != nil {
		return err
	}
	stream, err := s.Instances.Activity(r.Context(), id, userID(r), eventID)
	if err != nil {
		return err
	}
	return pipeSSE(w, stream, "activity", id)
}

// POST /api/instances/{id}/stop.
func (s *Server) stopInstance(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	if err := s.Instances.Stop(r.Context(), id, userID(r)); err != nil {
		return err
	}
	return noContent(w)
}

// POST /api/instances/{id}/raise.
func (s *Server) raiseInstance(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	queued, err := s.Instances.Raise(r.Context(), id, userID(r))
	if err != nil {
		return err
	}
	if queued {
		return respond(w, http.StatusAccepted, map[string]string{"status": "queued"})
	}
	return respond(w, http.StatusOK, map[string]string{"status": "running"})
}

// POST /api/instances/{id}/resume.
func (s *Server) resumeInstance(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	eventIDs, err := s.Instances.Resume(r.Context(), id, userID(r))
	if err != nil {
		return err
	}
	if eventIDs == nil {
		eventIDs = []int64{}
	}
	return respond(w, http.StatusOK, map[string][]int64{"eventIds": eventIDs})
}

// POST /api/instances/{id}/chat.
func (s *Server) instanceChat(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	var req struct {
		Message string `json:"message"`
	}
	if err := decode(r, &req); err != nil {
		return err
	}
	if req.Message == "" {
		return domain.Invalid("message is required")
	}
	stream, err := s.Instances.Chat(r.Context(), id, userID(r), req.Message)
	if err != nil {
		return err
	}
	return pipeSSE(w, stream, "chat", id)
}

// POST /api/instances/{id}/terminal.
func (s *Server) instanceTerminal(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r)
	if err != nil {
		return err
	}
	var req struct {
		Command string `json:"command"`
	}
	if err := decode(r, &req); err != nil {
		return err
	}
	if req.Command == "" {
		return domain.Invalid("command is required")
	}
	stream, err := s.Instances.Terminal(r.Context(), id, userID(r), req.Command)
	if err != nil {
		return err
	}
	return pipeSSE(w, stream, "terminal", id)
}
