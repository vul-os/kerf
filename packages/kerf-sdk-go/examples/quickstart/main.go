package main

import (
	"context"
	"fmt"
	"log"

	kerf "github.com/kerf-sh/kerf-sdk-go"
)

func main() {
	ctx := context.Background()

	// Reads KERF_API_TOKEN and KERF_API_URL from the environment.
	k, err := kerf.FromEnv()
	if err != nil {
		log.Fatal(err)
	}

	// List all files in a project.
	fileList, err := k.Files.List(ctx, "proj_123")
	if err != nil {
		log.Fatal(err)
	}
	fmt.Printf("Files (%d):\n", len(fileList))
	for _, f := range fileList {
		fmt.Printf("  %s  %s  [%s]\n", f.ID, f.Name, f.Kind)
	}

	// Read a specific file's content.
	content, err := k.Files.Read(ctx, "proj_123", "file_abc")
	if err != nil {
		log.Fatal(err)
	}
	fmt.Printf("\nFile content:\n%s\n", content.Content)

	// Set an equation variable.
	if err := k.Equations.Set(ctx, "proj_123", "file_abc", "width", "75"); err != nil {
		log.Fatal(err)
	}
	fmt.Println("\nEquation 'width' set to 75.")

	// Search the Kerf documentation.
	hits, err := k.Docs.Search(ctx, "how to use configurations", nil)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Printf("\nDoc results (%d):\n", len(hits))
	for _, h := range hits {
		fmt.Printf("  [%.2f] %s\n", h.Score, h.Title)
	}
}
