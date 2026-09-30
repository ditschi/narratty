package main

import (
	"bufio"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"sync"
)

// A connection starts with one JSON line from the client (the header). After it
// both sides exchange frames: a type byte, a big-endian uint32 length, the payload.
const (
	frameInput  = 'i' // client → server: keystrokes
	frameResize = 'r' // client → server: rows, cols (uint16 each)
	frameOutput = 'o' // server → client: terminal output
	frameExit   = 'x' // server → client: exit code (int32); last frame
	frameError  = 'e' // server → client: why the shell could not start; last frame
)

const maxFrame = 1 << 20

type header struct {
	Argv []string          `json:"argv,omitempty"`
	Env  map[string]string `json:"env,omitempty"`
	Cwd  string            `json:"cwd,omitempty"`
	Rows uint16            `json:"rows,omitempty"`
	Cols uint16            `json:"cols,omitempty"`
	Ping bool              `json:"ping,omitempty"`
}

func writeHeader(w io.Writer, h header) error {
	data, err := json.Marshal(h)
	if err != nil {
		return err
	}
	_, err = w.Write(append(data, '\n'))
	return err
}

func readHeader(r *bufio.Reader) (header, error) {
	var h header
	line, err := r.ReadBytes('\n')
	if err != nil {
		return h, fmt.Errorf("reading header: %w", err)
	}
	if err := json.Unmarshal(line, &h); err != nil {
		return h, fmt.Errorf("invalid header: %w", err)
	}
	return h, nil
}

// frameWriter serialises frames from several goroutines.
type frameWriter struct {
	mu sync.Mutex
	w  io.Writer
}

func (f *frameWriter) write(kind byte, payload []byte) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	var head [5]byte
	head[0] = kind
	binary.BigEndian.PutUint32(head[1:], uint32(len(payload)))
	if _, err := f.w.Write(head[:]); err != nil {
		return err
	}
	_, err := f.w.Write(payload)
	return err
}

func (f *frameWriter) exit(code int) error {
	var payload [4]byte
	binary.BigEndian.PutUint32(payload[:], uint32(int32(code)))
	return f.write(frameExit, payload[:])
}

func (f *frameWriter) resize(rows, cols uint16) error {
	var payload [4]byte
	binary.BigEndian.PutUint16(payload[:2], rows)
	binary.BigEndian.PutUint16(payload[2:], cols)
	return f.write(frameResize, payload[:])
}

func readFrame(r io.Reader) (byte, []byte, error) {
	var head [5]byte
	if _, err := io.ReadFull(r, head[:]); err != nil {
		return 0, nil, err
	}
	size := binary.BigEndian.Uint32(head[1:])
	if size > maxFrame {
		return 0, nil, errors.New("frame too large")
	}
	payload := make([]byte, size)
	if _, err := io.ReadFull(r, payload); err != nil {
		return 0, nil, err
	}
	return head[0], payload, nil
}

func decodeResize(payload []byte) (rows, cols uint16, ok bool) {
	if len(payload) != 4 {
		return 0, 0, false
	}
	return binary.BigEndian.Uint16(payload[:2]), binary.BigEndian.Uint16(payload[2:]), true
}

func decodeExit(payload []byte) int {
	if len(payload) != 4 {
		return 1
	}
	return int(int32(binary.BigEndian.Uint32(payload)))
}
