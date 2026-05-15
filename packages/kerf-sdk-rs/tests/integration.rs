//! Integration tests using `wiremock` to stub the JSON-RPC server.
//!
//! Each test spins up an in-process mock HTTP server, constructs a [`Kerf`]
//! client pointed at it, and exercises the full call → parse → return path.

use kerf_sdk::{KerfError, Kerf};
use serde_json::json;
use wiremock::matchers::{header, method, path};
use wiremock::{Mock, MockServer, ResponseTemplate};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Build a well-formed JSON-RPC success response body.
fn rpc_ok(result: serde_json::Value) -> serde_json::Value {
    json!({ "jsonrpc": "2.0", "id": "1", "result": result })
}

/// Build a JSON-RPC error response body.
fn rpc_err(code: i32, message: &str) -> serde_json::Value {
    json!({
        "jsonrpc": "2.0",
        "id": "1",
        "error": { "code": code, "message": message }
    })
}

/// Construct a [`Kerf`] client wired to the given mock server.
fn client(server: &MockServer) -> Kerf {
    Kerf::new(&server.uri(), "ktok_test_token").expect("client construction failed")
}

// ---------------------------------------------------------------------------
// Auth header
// ---------------------------------------------------------------------------

#[tokio::test]
async fn auth_header_is_sent_on_every_request() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/v1/rpc"))
        .and(header("authorization", "Bearer ktok_test_token"))
        .respond_with(ResponseTemplate::new(200).set_body_json(rpc_ok(json!([]))))
        .mount(&server)
        .await;

    let k = client(&server);
    k.files.list("proj_1").await.unwrap();
}

// ---------------------------------------------------------------------------
// files namespace
// ---------------------------------------------------------------------------

#[tokio::test]
async fn files_list_returns_vec() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/v1/rpc"))
        .respond_with(ResponseTemplate::new(200).set_body_json(rpc_ok(json!([
            { "id": "f1", "name": "part.jscad", "kind": "source" }
        ]))))
        .mount(&server)
        .await;

    let k = client(&server);
    let files = k.files.list("proj_1").await.unwrap();
    assert_eq!(files.len(), 1);
    assert_eq!(files[0].name, "part.jscad");
}

#[tokio::test]
async fn files_read_returns_content() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/v1/rpc"))
        .respond_with(ResponseTemplate::new(200).set_body_json(rpc_ok(json!({
            "id": "f1", "name": "part.jscad", "kind": "source",
            "content": "// hello world"
        }))))
        .mount(&server)
        .await;

    let k = client(&server);
    let fc = k.files.read("proj_1", "f1").await.unwrap();
    assert_eq!(fc.content, "// hello world");
}

#[tokio::test]
async fn files_write_returns_ok() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/v1/rpc"))
        .respond_with(ResponseTemplate::new(200).set_body_json(rpc_ok(json!({ "ok": true }))))
        .mount(&server)
        .await;

    let k = client(&server);
    let result = k.files.write("proj_1", "f1", "new content").await.unwrap();
    assert!(result.ok);
}

#[tokio::test]
async fn files_create_returns_file_info() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/v1/rpc"))
        .respond_with(ResponseTemplate::new(200).set_body_json(rpc_ok(json!({
            "id": "f2", "name": "new.jscad", "kind": "source"
        }))))
        .mount(&server)
        .await;

    let k = client(&server);
    let fi = k.files.create("proj_1", "new.jscad", "source", "", None).await.unwrap();
    assert_eq!(fi.id, "f2");
}

#[tokio::test]
async fn files_delete_returns_ok() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/v1/rpc"))
        .respond_with(ResponseTemplate::new(200).set_body_json(rpc_ok(json!({ "ok": true }))))
        .mount(&server)
        .await;

    let k = client(&server);
    let result = k.files.delete("proj_1", "f1").await.unwrap();
    assert!(result.ok);
}

// ---------------------------------------------------------------------------
// equations namespace
// ---------------------------------------------------------------------------

#[tokio::test]
async fn equations_read_returns_map() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/v1/rpc"))
        .respond_with(ResponseTemplate::new(200).set_body_json(rpc_ok(json!({
            "equations": [{ "name": "width", "expression": "10 mm" }]
        }))))
        .mount(&server)
        .await;

    let k = client(&server);
    let eq = k.equations.read("proj_1", "f1").await.unwrap();
    assert_eq!(eq.equations[0].name, "width");
}

// ---------------------------------------------------------------------------
// revisions namespace
// ---------------------------------------------------------------------------

#[tokio::test]
async fn revisions_list_returns_vec() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/v1/rpc"))
        .respond_with(ResponseTemplate::new(200).set_body_json(rpc_ok(json!([
            { "id": "rev_1", "created_at": "2024-01-01T00:00:00Z" }
        ]))))
        .mount(&server)
        .await;

    let k = client(&server);
    let revs = k.revisions.list("proj_1", "f1", None).await.unwrap();
    assert_eq!(revs[0].id, "rev_1");
}

// ---------------------------------------------------------------------------
// docs namespace
// ---------------------------------------------------------------------------

#[tokio::test]
async fn docs_search_returns_hits() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/v1/rpc"))
        .respond_with(ResponseTemplate::new(200).set_body_json(rpc_ok(json!([
            { "title": "Assemblies", "snippet": "How to create assemblies", "url": "/docs/assemblies" }
        ]))))
        .mount(&server)
        .await;

    let k = client(&server);
    let hits = k.docs.search("assemblies", None).await.unwrap();
    assert_eq!(hits[0].title, "Assemblies");
}

// ---------------------------------------------------------------------------
// Error mapping
// ---------------------------------------------------------------------------

#[tokio::test]
async fn rpc_error_401_maps_to_unauthorized() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/v1/rpc"))
        .respond_with(ResponseTemplate::new(200).set_body_json(rpc_err(-32001, "unauthorized")))
        .mount(&server)
        .await;

    let k = client(&server);
    let err = k.files.list("proj_1").await.unwrap_err();
    assert!(
        matches!(err, KerfError::Unauthorized),
        "expected Unauthorized, got {err:?}"
    );
}

#[tokio::test]
async fn rpc_error_404_maps_to_not_found() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/v1/rpc"))
        .respond_with(ResponseTemplate::new(200).set_body_json(rpc_err(-32004, "not found")))
        .mount(&server)
        .await;

    let k = client(&server);
    let err = k.files.read("proj_1", "missing").await.unwrap_err();
    assert!(
        matches!(err, KerfError::NotFound),
        "expected NotFound, got {err:?}"
    );
}

#[tokio::test]
async fn rpc_error_429_maps_to_rate_limited() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/v1/rpc"))
        .respond_with(ResponseTemplate::new(200).set_body_json(rpc_err(-32029, "too many requests")))
        .mount(&server)
        .await;

    let k = client(&server);
    let err = k.files.list("proj_1").await.unwrap_err();
    assert!(
        matches!(err, KerfError::RateLimited),
        "expected RateLimited, got {err:?}"
    );
}

#[tokio::test]
async fn generic_rpc_error_maps_to_rpc_error_variant() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/v1/rpc"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(rpc_err(-32600, "invalid request")),
        )
        .mount(&server)
        .await;

    let k = client(&server);
    let err = k.files.list("proj_1").await.unwrap_err();
    assert!(
        matches!(err, KerfError::RpcError { code: -32600, .. }),
        "expected RpcError(-32600), got {err:?}"
    );
}

// ---------------------------------------------------------------------------
// from_env
// ---------------------------------------------------------------------------

#[test]
fn from_env_errors_on_missing_token() {
    // Ensure both vars are absent for isolation
    std::env::remove_var("KERF_API_TOKEN");
    std::env::remove_var("KERF_API_URL");
    let err = Kerf::from_env().unwrap_err();
    // Either KERF_API_URL or KERF_API_TOKEN missing triggers MissingEnv
    assert!(matches!(err, KerfError::MissingEnv(_)));
}

#[test]
fn from_env_errors_on_missing_url() {
    std::env::set_var("KERF_API_TOKEN", "ktok_something");
    std::env::remove_var("KERF_API_URL");
    let err = Kerf::from_env().unwrap_err();
    assert!(matches!(err, KerfError::MissingEnv("KERF_API_URL")));
    std::env::remove_var("KERF_API_TOKEN");
}
