//! # kerf-sdk
//!
//! Async Rust client for the [Kerf](https://kerf.sh) CAD platform JSON-RPC API.
//!
//! ## Quickstart
//!
//! ```no_run
//! use kerf_sdk::Kerf;
//!
//! #[tokio::main]
//! async fn main() -> Result<(), Box<dyn std::error::Error>> {
//!     let k = Kerf::from_env()?;
//!     let files = k.files.list("proj_123").await?;
//!     println!("{:#?}", files);
//!     Ok(())
//! }
//! ```
//!
//! ## Auth
//!
//! Set `KERF_API_URL` and `KERF_API_TOKEN` before calling [`Kerf::from_env`], or
//! use [`Kerf::new`] to pass credentials directly.
//!
//! ## Namespaces
//!
//! | Field | Description |
//! |-------|-------------|
//! | [`Kerf::files`] | Create, read, write, delete, search files |
//! | [`Kerf::equations`] | Read and set parametric equations |
//! | [`Kerf::configurations`] | Add configurations, switch active config |
//! | [`Kerf::revisions`] | Browse file history, restore revisions |
//! | [`Kerf::docs`] | Search the Kerf documentation |

pub mod configurations;
pub mod docs;
pub mod equations;
pub mod error;
pub mod files;
pub mod revisions;
pub mod types;

mod auth;
mod client;

pub use configurations::Configurations;
pub use docs::Docs;
pub use equations::Equations;
pub use error::KerfError;
pub use files::Files;
pub use revisions::Revisions;
pub use types::*;

use crate::client::Client;

/// Top-level Kerf client.
///
/// Construct via [`Kerf::from_env`] or [`Kerf::new`], then access the
/// namespaced sub-clients through public fields.
#[derive(Clone, Debug)]
pub struct Kerf {
    /// File operations — list, read, write, create, delete, search.
    pub files: Files,
    /// Equation operations — read, set.
    pub equations: Equations,
    /// Configuration operations — list, add, activate.
    pub configurations: Configurations,
    /// Revision history — list, read, restore.
    pub revisions: Revisions,
    /// Documentation search.
    pub docs: Docs,
}

impl Kerf {
    /// Construct from an explicit API URL and Bearer token.
    ///
    /// `api_url` must include the scheme (e.g. `https://kerf.sh`). A trailing
    /// slash is stripped automatically.
    ///
    /// ```no_run
    /// use kerf_sdk::Kerf;
    ///
    /// # async fn example() -> Result<(), kerf_sdk::KerfError> {
    /// let k = Kerf::new("https://kerf.sh", "ktok_my_token")?;
    /// # Ok(())
    /// # }
    /// ```
    pub fn new(api_url: &str, token: &str) -> Result<Self, KerfError> {
        let api_url = api_url.trim_end_matches('/').to_owned();
        let inner = Client::new(&api_url, token)?;
        Ok(Self::from_client(inner))
    }

    /// Construct from environment variables.
    ///
    /// Required variables:
    /// - `KERF_API_URL` — e.g. `https://kerf.sh` (no trailing slash needed)
    /// - `KERF_API_TOKEN` — API token starting with `ktok_`
    ///
    /// Returns [`KerfError::MissingEnv`] if either variable is absent or empty.
    pub fn from_env() -> Result<Self, KerfError> {
        let url = auth::load_url()?;
        let token = auth::load_token()?;
        let inner = Client::new(&url, &token)?;
        Ok(Self::from_client(inner))
    }

    fn from_client(c: Client) -> Self {
        Self {
            files: Files { client: c.clone() },
            equations: Equations { client: c.clone() },
            configurations: Configurations { client: c.clone() },
            revisions: Revisions { client: c.clone() },
            docs: Docs { client: c },
        }
    }
}
