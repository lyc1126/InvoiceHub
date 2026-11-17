pub mod app_icon;
pub mod backend;
pub mod host_rpc;
mod local_http;
pub mod monitor_bridge;
pub mod monitor_recovery;
pub mod startup_diagnostics;
pub mod update_coordinator;

pub const FIXED_BACKEND_HOST: &str = "127.0.0.1";
pub const FIXED_BACKEND_PORT: u16 = 8766;

pub fn backend_origin() -> String {
    format!("http://{FIXED_BACKEND_HOST}:{FIXED_BACKEND_PORT}")
}

pub fn accepts_temporary_file_drop(url: &tauri::Url) -> bool {
    // The Vue temporary page shares the original selection service. State queries
    // must not disable drops or grant another workspace module access to paths.
    url.scheme() == "http"
        && url.host_str() == Some(FIXED_BACKEND_HOST)
        && url.port() == Some(FIXED_BACKEND_PORT)
        && url.username().is_empty()
        && url.password().is_none()
        && matches!(
            url.path(),
            "/" | "/workspace/temporary" | "/workspace/temporary/"
        )
}

#[cfg(test)]
mod tests {
    use super::{backend_origin, FIXED_BACKEND_HOST, FIXED_BACKEND_PORT};

    #[test]
    fn backend_origin_is_the_fixed_localhost_contract() {
        assert_eq!(FIXED_BACKEND_HOST, "127.0.0.1");
        assert_eq!(FIXED_BACKEND_PORT, 8766);
        assert_eq!(backend_origin(), "http://127.0.0.1:8766");
    }

    #[test]
    fn native_file_drop_accepts_home_state_only_on_the_fixed_origin() {
        for value in [
            "http://127.0.0.1:8766/",
            "http://127.0.0.1:8766/?selection_return=test&no_skin=1",
            "http://127.0.0.1:8766/workspace/temporary?no_skin=1",
            "http://127.0.0.1:8766/workspace/temporary/",
        ] {
            assert!(super::accepts_temporary_file_drop(&value.parse().unwrap()));
        }
        for value in [
            "https://127.0.0.1:8766/",
            "http://127.0.0.1:8767/",
            "http://localhost:8766/",
            "http://127.0.0.1:8766/invoices/0",
            "http://127.0.0.1:8766/workspace/",
            "http://127.0.0.1:8766/workspace/costs",
            "http://user@127.0.0.1:8766/",
            "http://example.org/",
        ] {
            assert!(!super::accepts_temporary_file_drop(&value.parse().unwrap()));
        }
    }
}
