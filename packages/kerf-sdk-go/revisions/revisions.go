// Package revisions provides file history browsing and restoration via the Kerf JSON-RPC API.
package revisions

import (
	"context"
)

// Caller is the JSON-RPC transport interface satisfied by *kerf.httpClient.
type Caller interface {
	Call(ctx context.Context, method string, params any, dst any) error
}

// Client wraps the JSON-RPC caller with revision-scoped methods.
type Client struct {
	c Caller
}

// NewClient constructs a revisions.Client backed by the given Caller.
func NewClient(c Caller) *Client {
	return &Client{c: c}
}

// Revision describes a single point-in-time snapshot of a file.
type Revision struct {
	ID        string `json:"id"`
	FileID    string `json:"file_id"`
	CreatedAt string `json:"created_at"`
	Message   string `json:"message,omitempty"`
}

// ListOptions holds optional parameters for List.
type ListOptions struct {
	// Limit caps the number of revisions returned. Zero means server default.
	Limit int
	// Before filters to revisions created before this RFC 3339 timestamp.
	Before string
}

// List returns the revision history for a file.
// Pass opts to filter or page the results; nil is valid and uses server defaults.
func (c *Client) List(ctx context.Context, projectID, fileID string, opts *ListOptions) ([]Revision, error) {
	params := map[string]any{
		"project_id": projectID,
		"file_id":    fileID,
	}
	if opts != nil {
		if opts.Limit > 0 {
			params["limit"] = opts.Limit
		}
		if opts.Before != "" {
			params["before"] = opts.Before
		}
	}
	var result []Revision
	err := c.c.Call(ctx, "revisions.list", params, &result)
	return result, err
}

// Read returns a specific revision of a file.
func (c *Client) Read(ctx context.Context, projectID, fileID, revisionID string) (*Revision, error) {
	var result Revision
	err := c.c.Call(ctx, "revisions.read", map[string]any{
		"project_id":  projectID,
		"file_id":     fileID,
		"revision_id": revisionID,
	}, &result)
	return &result, err
}

// Restore rolls a file back to the given revision.
func (c *Client) Restore(ctx context.Context, projectID, fileID, revisionID string) error {
	return c.c.Call(ctx, "revisions.restore", map[string]any{
		"project_id":  projectID,
		"file_id":     fileID,
		"revision_id": revisionID,
	}, nil)
}
