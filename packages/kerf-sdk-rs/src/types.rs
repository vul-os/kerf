use serde::{Deserialize, Serialize};
use serde_json::Value;

// ---------------------------------------------------------------------------
// Files
// ---------------------------------------------------------------------------

/// Metadata for a file entry returned by `files.list` or `files.create`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileInfo {
    pub id: String,
    pub name: String,
    pub kind: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parent_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub updated_at: Option<String>,
    /// Catch-all for extra fields the server may return.
    #[serde(flatten)]
    pub extra: std::collections::HashMap<String, Value>,
}

/// Full file content + metadata returned by `files.read`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileContent {
    pub id: String,
    pub name: String,
    pub kind: String,
    pub content: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parent_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub updated_at: Option<String>,
    #[serde(flatten)]
    pub extra: std::collections::HashMap<String, Value>,
}

/// Acknowledgement returned by write / delete operations.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OkResult {
    pub ok: bool,
}

// ---------------------------------------------------------------------------
// Equations
// ---------------------------------------------------------------------------

/// One equation entry.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Equation {
    pub name: String,
    pub expression: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub value: Option<Value>,
}

/// The full equations map returned by `equations.read`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EquationsMap {
    /// Individual equation entries.
    #[serde(default)]
    pub equations: Vec<Equation>,
    #[serde(flatten)]
    pub extra: std::collections::HashMap<String, Value>,
}

// ---------------------------------------------------------------------------
// Configurations
// ---------------------------------------------------------------------------

/// One configuration entry.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Configuration {
    pub id: String,
    pub label: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub is_active: Option<bool>,
    #[serde(flatten)]
    pub extra: std::collections::HashMap<String, Value>,
}

// ---------------------------------------------------------------------------
// Revisions
// ---------------------------------------------------------------------------

/// Summary of a single revision.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RevisionInfo {
    pub id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub created_at: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub author: Option<String>,
    #[serde(flatten)]
    pub extra: std::collections::HashMap<String, Value>,
}

/// File content at a specific revision.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RevisionContent {
    pub id: String,
    pub content: String,
    #[serde(flatten)]
    pub extra: std::collections::HashMap<String, Value>,
}

// ---------------------------------------------------------------------------
// Docs
// ---------------------------------------------------------------------------

/// One search hit from `docs.search`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocHit {
    pub title: String,
    pub snippet: String,
    pub url: String,
    #[serde(flatten)]
    pub extra: std::collections::HashMap<String, Value>,
}
