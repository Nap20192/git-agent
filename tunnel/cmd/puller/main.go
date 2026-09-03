// Command puller — локальный клиент релея: длинный поллинг RELAY_URL/pull,
// каждую запись переигрывает в hub с исходными путём/заголовками/телом,
// так что HMAC-подпись провайдера доезжает нетронутой.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"strings"
	"time"
)

type record struct {
	Path    string      `json:"path"`
	Headers http.Header `json:"headers"`
	Body    []byte      `json:"body"`
}

// Заголовки соединения не переигрываем — их выставляет http.Client.
var skipHeaders = map[string]bool{"Host": true, "Content-Length": true, "Connection": true, "Accept-Encoding": true}

func pull(client *http.Client, relayURL, token string) ([]record, error) {
	req, err := http.NewRequest("GET", relayURL+"/pull?wait=25s", nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("X-Relay-Token", token)
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("relay: %s", resp.Status)
	}
	var recs []record
	return recs, json.NewDecoder(resp.Body).Decode(&recs)
}

func replay(client *http.Client, hubURL string, rec record) error {
	req, err := http.NewRequest("POST", hubURL+rec.Path, bytes.NewReader(rec.Body))
	if err != nil {
		return err
	}
	for k, vs := range rec.Headers {
		if ck := http.CanonicalHeaderKey(k); !skipHeaders[ck] {
			req.Header[ck] = vs
		}
	}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	resp.Body.Close()
	if resp.StatusCode >= 300 {
		return fmt.Errorf("hub: %s", resp.Status)
	}
	return nil
}

func main() {
	relayURL := strings.TrimSuffix(os.Getenv("RELAY_URL"), "/")
	token := os.Getenv("RELAY_TOKEN")
	if relayURL == "" || token == "" {
		log.Fatal("puller: RELAY_URL and RELAY_TOKEN are required")
	}
	hubURL := strings.TrimSuffix(os.Getenv("HUB_URL"), "/")
	if hubURL == "" {
		hubURL = "http://localhost:8081"
	}
	client := &http.Client{Timeout: 60 * time.Second}
	log.Printf("puller: %s -> %s", relayURL, hubURL)
	for {
		recs, err := pull(client, relayURL, token)
		if err != nil {
			log.Printf("puller: pull failed: %v", err)
			time.Sleep(3 * time.Second)
			continue
		}
		for _, rec := range recs {
			if err := replay(client, hubURL, rec); err != nil {
				log.Printf("puller: replay %s failed: %v", rec.Path, err)
			}
		}
	}
}
