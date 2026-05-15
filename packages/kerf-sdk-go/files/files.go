// Package files provides operations on project files via the Kerf JSON-RPC API.
package files

import (
	"context"
)

// Caller is the JSON-RPC transport interface satisfied by *kerf.httpClient.
// Defined here to avoid an import cycle back to the root package.
type Caller interface {
	Call(ctx context.Context, method string, params any, dst any) error
}

// Client wraps the JSON-RPC caller with file-scoped methods.
type Client struct {
	c Caller
}

// NewClient constructs a files.Client backed by the given Caller.
func NewClient(c Caller) *Client {
	return &Client{c: c}
}

// FileInfo describes a file entry.
type FileInfo struct {
	ID       string `json:"id"`
	Name     string `json:"name"`
	Kind     string `json:"kind"`
	ParentID string `json:"parent_id,omitempty"`
}

// FileContent holds the full content of a file.
type FileContent struct {
	ID      string `json:"id"`
	Name    string `json:"name"`
	Kind    string `json:"kind"`
	Content string `json:"content"`
}

// WriteResult is returned by Write and Edit.
type WriteResult struct {
	OK         bool   `json:"ok"`
	RevisionID string `json:"revision_id,omitempty"`
}

// CreateOptions holds optional parameters for Create.
type CreateOptions struct {
	// Kind defaults to "file" when empty.
	Kind string
	// Content is the initial file body.
	Content string
	// ParentID places the new file under a folder.
	ParentID string
}

// List returns all files in the given project.
func (c *Client) List(ctx context.Context, projectID string) ([]FileInfo, error) {
	var result []FileInfo
	err := c.c.Call(ctx, "files.list", map[string]any{"project_id": projectID}, &result)
	return result, err
}

// Read returns the content of a specific file.
func (c *Client) Read(ctx context.Context, projectID, fileID string) (*FileContent, error) {
	var result FileContent
	err := c.c.Call(ctx, "files.read", map[string]any{
		"project_id": projectID,
		"file_id":    fileID,
	}, &result)
	return &result, err
}

// Write replaces the full content of a file.
func (c *Client) Write(ctx context.Context, projectID, fileID, content string) (*WriteResult, error) {
	var result WriteResult
	err := c.c.Call(ctx, "files.write", map[string]any{
		"project_id": projectID,
		"file_id":    fileID,
		"content":    content,
	}, &result)
	return &result, err
}

// Edit performs a string-replace within a file (old_string → new_string).
func (c *Client) Edit(ctx context.Context, projectID, fileID, oldString, newString string) (*WriteResult, error) {
	var result WriteResult
	err := c.c.Call(ctx, "files.edit", map[string]any{
		"project_id": projectID,
		"file_id":    fileID,
		"old_string": oldString,
		"new_string": newString,
	}, &result)
	return &result, err
}

// Create adds a new file (or folder) to the project.
// Use opts to specify kind, initial content, and parent folder.
func (c *Client) Create(ctx context.Context, projectID, name string, opts *CreateOptions) (*FileInfo, error) {
	params := map[string]any{
		"project_id": projectID,
		"name":       name,
		"kind":       "file",
		"content":    "",
	}
	if opts != nil {
		if opts.Kind != "" {
			params["kind"] = opts.Kind
		}
		if opts.Content != "" {
			params["content"] = opts.Content
		}
		if opts.ParentID != "" {
			params["parent_id"] = opts.ParentID
		}
	}
	var result FileInfo
	err := c.c.Call(ctx, "files.create", params, &result)
	return &result, err
}

// Delete removes a file from the project.
func (c *Client) Delete(ctx context.Context, projectID, fileID string) error {
	return c.c.Call(ctx, "files.delete", map[string]any{
		"project_id": projectID,
		"file_id":    fileID,
	}, nil)
}

// Search performs a full-text search within project files.
func (c *Client) Search(ctx context.Context, projectID, query string) ([]FileInfo, error) {
	var result []FileInfo
	err := c.c.Call(ctx, "files.search", map[string]any{
		"project_id": projectID,
		"query":      query,
	}, &result)
	return result, err
}
