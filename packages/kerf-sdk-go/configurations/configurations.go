// Package configurations manages named parameter configurations via the Kerf JSON-RPC API.
package configurations

import (
	"context"
)

// Caller is the JSON-RPC transport interface satisfied by *kerf.httpClient.
type Caller interface {
	Call(ctx context.Context, method string, params any, dst any) error
}

// Client wraps the JSON-RPC caller with configuration-scoped methods.
type Client struct {
	c Caller
}

// NewClient constructs a configurations.Client backed by the given Caller.
func NewClient(c Caller) *Client {
	return &Client{c: c}
}

// Configuration describes a named parameter configuration.
type Configuration struct {
	ID     string         `json:"id"`
	Label  string         `json:"label"`
	Params map[string]any `json:"params"`
}

// List returns all configurations for the given project file.
func (c *Client) List(ctx context.Context, projectID, fileID string) ([]Configuration, error) {
	var result []Configuration
	err := c.c.Call(ctx, "configurations.list", map[string]any{
		"project_id": projectID,
		"file_id":    fileID,
	}, &result)
	return result, err
}

// Add creates a new configuration with a label and parameter map.
func (c *Client) Add(ctx context.Context, projectID, fileID, label string, params map[string]any) (*Configuration, error) {
	var result Configuration
	err := c.c.Call(ctx, "configurations.add", map[string]any{
		"project_id": projectID,
		"file_id":    fileID,
		"label":      label,
		"params":     params,
	}, &result)
	return &result, err
}

// Activate sets the active configuration for a file.
func (c *Client) Activate(ctx context.Context, projectID, fileID, configID string) error {
	return c.c.Call(ctx, "configurations.set_active", map[string]any{
		"project_id": projectID,
		"file_id":    fileID,
		"config_id":  configID,
	}, nil)
}
