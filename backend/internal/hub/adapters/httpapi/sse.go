package httpapi

import (
	"context"
	"errors"
	"io"
	"net/http"

	"go.uber.org/zap"
)

func pipeSSE(w http.ResponseWriter, stream io.ReadCloser, label string, id int64) error {
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
				return nil // клиент отвалился
			}
			if flusher != nil {
				flusher.Flush()
			}
		}
		if err == nil {
			continue
		}
		if err != io.EOF {
			if errors.Is(err, context.Canceled) {
				zap.S().Infow("instances: "+label+" stream closed by client", "instanceId", id)
			} else {
				zap.S().Warnw("instances: "+label+" stream interrupted", "instanceId", id, "err", err)
			}
		}
		return nil
	}
}
