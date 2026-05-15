// Package equations provides access to equation variables via the Kerf JSON-RPC API.
package equations

import (
	"context"
)

// Caller is the JSON-RPC transport interface satisfied by *kerf.httpClient.
type Caller interface {
	Call(ctx context.Context, method string, params any, dst any) error
}

// Client wraps the JSON-RPC caller with equation-scoped methods.
type Client struct {
	c Caller
}

// NewClient constructs an equations.Client backed by the given Caller.
func NewClient(c Caller) *Client {
	return &Client{c: c}
}

// Equation describes a single equation variable.
type Equation struct {
	Name       string `json:"name"`
	Expression string `json:"expression"`
	Value      any    `json:"value,omitempty"`
}

// Read returns all equation variables for the given project file.
func (c *Client) Read(ctx context.Context, projectID, fileID string) ([]Equation, error) {
	var result []Equation
	err := c.c.Call(ctx, "equations.read", map[string]any{
		"project_id": projectID,
		"file_id":    fileID,
	}, &result)
	return result, err
}

// Set creates or updates a named equation variable.
func (c *Client) Set(ctx context.Context, projectID, fileID, name, expression string) error {
	return c.c.Call(ctx, "equations.set", map[string]any{
		"project_id": projectID,
		"file_id":    fileID,
		"name":       name,
		"expression": expression,
	}, nil)
}
