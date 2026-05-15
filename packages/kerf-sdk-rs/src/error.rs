/// All errors that can be returned by the Kerf SDK.
///
/// JSON-RPC error codes follow the server's convention:
/// - `-32700` parse error
/// - `-32600` invalid request / project not found / access denied
/// - `-32601` method not found
/// - `-32602` invalid params
/// - `-32603` internal error
///
/// HTTP-level codes map directly: 401 → [`KerfError::Unauthorized`],
/// 404 → [`KerfError::NotFound`], 429 → [`KerfError::RateLimited`].
#[derive(thiserror::Error, Debug)]
pub enum KerfError {
    /// Underlying HTTP transport error from `reqwest`.
    #[error("HTTP error: {0}")]
    Http(#[from] reqwest::Error),

    /// The server returned a JSON-RPC `error` object.
    #[error("JSON-RPC error {code}: {message}")]
    RpcError {
        code: i32,
        message: String,
        data: Option<serde_json::Value>,
    },

    /// The response body could not be parsed or was malformed.
    #[error("invalid response: {0}")]
    InvalidResponse(String),

    /// The API token was rejected (HTTP 401 or RPC code -32001).
    #[error("authentication failed")]
    Unauthorized,

    /// The requested resource does not exist (HTTP 404 or RPC code -32004).
    #[error("not found")]
    NotFound,

    /// Too many requests (HTTP 429 or RPC code -32029).
    #[error("rate limited")]
    RateLimited,

    /// A required environment variable is absent.
    #[error("missing environment variable: {0}")]
    MissingEnv(&'static str),
}

impl KerfError {
    /// Map a JSON-RPC error code + message to the most specific variant.
    pub(crate) fn from_rpc(code: i32, message: String, data: Option<serde_json::Value>) -> Self {
        match code {
            -32001 | 401 => KerfError::Unauthorized,
            -32004 | 404 => KerfError::NotFound,
            -32029 | 429 => KerfError::RateLimited,
            _ => KerfError::RpcError { code, message, data },
        }
    }
}
