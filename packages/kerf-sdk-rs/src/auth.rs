use crate::KerfError;

/// Read `KERF_API_TOKEN` from the environment.
///
/// Returns [`KerfError::MissingEnv`] if the variable is absent or empty.
pub(crate) fn load_token() -> Result<String, KerfError> {
    let token = std::env::var("KERF_API_TOKEN").unwrap_or_default();
    let token = token.trim().to_owned();
    if token.is_empty() {
        return Err(KerfError::MissingEnv("KERF_API_TOKEN"));
    }
    Ok(token)
}

/// Read `KERF_API_URL` from the environment.
///
/// Returns [`KerfError::MissingEnv`] if the variable is absent or empty —
/// there is no default URL so that scripts must be explicit about which server
/// they target.
pub(crate) fn load_url() -> Result<String, KerfError> {
    let url = std::env::var("KERF_API_URL").unwrap_or_default();
    let url = url.trim().trim_end_matches('/').to_owned();
    if url.is_empty() {
        return Err(KerfError::MissingEnv("KERF_API_URL"));
    }
    Ok(url)
}
