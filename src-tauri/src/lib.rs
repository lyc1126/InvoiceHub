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
    // A detail-return token and no_skin only change homepage state; they must
    // not disable native drops or broaden the event to other origins/pages.
    url.scheme() == "http"
        && url.host_str() == Some(FIXED_BACKEND_HOST)
        && url.port() == Some(FIXED_BACKEND_PORT)
        && url.username().is_empty()
        && url.password().is_none()
        && url.path() == "/"
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
        ] {
            assert!(super::accepts_temporary_file_drop(&value.parse().unwrap()));
        }
        for value in [
            "https://127.0.0.1:8766/",
            "http://127.0.0.1:8767/",
            "http://localhost:8766/",
            "http://127.0.0.1:8766/invoices/0",
            "http://user@127.0.0.1:8766/",
            "http://example.org/",
        ] {
            assert!(!super::accepts_temporary_file_drop(&value.parse().unwrap()));
        }
    }
}
