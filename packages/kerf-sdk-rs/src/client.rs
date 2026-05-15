use reqwest::Client as HttpClient;
use serde::{de::DeserializeOwned, Serialize};
use serde_json::{json, Value};
use uuid::Uuid;

use crate::KerfError;

/// Internal JSON-RPC response envelope.
#[derive(serde::Deserialize)]
struct RpcResponse {
    result: Option<Value>,
    error: Option<RpcErrorObject>,
}

#[derive(serde::Deserialize)]
struct RpcErrorObject {
    code: i32,
    message: String,
    data: Option<Value>,
}

/// Low-level HTTP client that handles JSON-RPC 2.0 envelope wrapping.
///
/// All namespace structs ([`crate::Files`], etc.) hold a clone of this.
/// The inner `reqwest::Client` is cheaply cloneable (it is an `Arc` internally).
#[derive(Clone, Debug)]
pub(crate) struct Client {
    pub(crate) api_url: String,
    http: HttpClient,
}

impl Client {
    /// Construct from an explicit URL + Bearer token.
    pub(crate) fn new(api_url: impl Into<String>, token: impl AsRef<str>) -> Result<Self, KerfError> {
        let mut headers = reqwest::header::HeaderMap::new();
        let bearer = format!("Bearer {}", token.as_ref());
        headers.insert(
            reqwest::header::AUTHORIZATION,
            bearer.parse().map_err(|_| {
                KerfError::InvalidResponse("invalid token characters".into())
            })?,
        );

        let http = HttpClient::builder()
            .default_headers(headers)
            .timeout(std::time::Duration::from_secs(30))
            .build()?;

        Ok(Self {
            api_url: api_url.into(),
            http,
        })
    }

    /// Send a JSON-RPC 2.0 call and deserialise the `result` field.
    ///
    /// Maps JSON-RPC error objects to [`KerfError`] variants.
    pub(crate) async fn call<P, R>(&self, method: &str, params: P) -> Result<R, KerfError>
    where
        P: Serialize,
        R: DeserializeOwned,
    {
        let envelope = json!({
            "jsonrpc": "2.0",
            "id": Uuid::new_v4().to_string(),
            "method": method,
            "params": params,
        });

        let response = self
            .http
            .post(format!("{}/v1/rpc", self.api_url))
            .json(&envelope)
            .send()
            .await?;

        // Propagate HTTP-level errors (4xx/5xx) as KerfError::Http via raise_for_status.
        // We handle 401/404/429 at the JSON-RPC layer too, but some servers send raw
        // HTTP errors for auth failures before parsing the body.
        let response = response.error_for_status()?;

        let body: RpcResponse = response.json().await.map_err(|e| {
            KerfError::InvalidResponse(format!("failed to parse response: {e}"))
        })?;

        if let Some(err) = body.error {
            return Err(KerfError::from_rpc(err.code, err.message, err.data));
        }

        match body.result {
            Some(v) => serde_json::from_value(v).map_err(|e| {
                KerfError::InvalidResponse(format!("unexpected result shape: {e}"))
            }),
            None => Err(KerfError::InvalidResponse(
                "response contained neither result nor error".into(),
            )),
        }
    }
}
