// Package docs provides full-text search across the Kerf documentation.
package docs

import (
	"context"
)

// Caller is the JSON-RPC transport interface satisfied by *kerf.httpClient.
type Caller interface {
	Call(ctx context.Context, method string, params any, dst any) error
}

// Client wraps the JSON-RPC caller with docs-scoped methods.
type Client struct {
	c Caller
}

// NewClient constructs a docs.Client backed by the given Caller.
func NewClient(c Caller) *Client {
	return &Client{c: c}
}

// DocResult describes a single document search hit.
type DocResult struct {
	ID      string  `json:"id"`
	Title   string  `json:"title"`
	Excerpt string  `json:"excerpt"`
	Score   float64 `json:"score"`
	URL     string  `json:"url,omitempty"`
}

// SearchOptions holds optional parameters for Search.
type SearchOptions struct {
	// K is the maximum number of results to return. Zero uses the server default.
	K int
}

// Search performs a semantic/full-text search across the Kerf docs.
// Pass opts to control result count; nil is valid.
func (c *Client) Search(ctx context.Context, query string, opts *SearchOptions) ([]DocResult, error) {
	params := map[string]any{"query": query}
	if opts != nil && opts.K > 0 {
		params["k"] = opts.K
	}
	var result []DocResult
	err := c.c.Call(ctx, "docs.search", params, &result)
	return result, err
}
