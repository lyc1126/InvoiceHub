pub const FIXED_BACKEND_HOST: &str = "127.0.0.1";
pub const FIXED_BACKEND_PORT: u16 = 8766;

pub fn backend_origin() -> String {
    format!("http://{FIXED_BACKEND_HOST}:{FIXED_BACKEND_PORT}")
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
}
