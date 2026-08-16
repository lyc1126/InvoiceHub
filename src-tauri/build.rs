fn main() {
    const MANIFEST_SHA_ENV: &str = "INVOICE_HUB_BUNDLE_MANIFEST_SHA256";
    println!("cargo:rerun-if-env-changed={MANIFEST_SHA_ENV}");
    if let Ok(digest) = std::env::var(MANIFEST_SHA_ENV) {
        if digest.len() != 64
            || !digest
                .bytes()
                .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
        {
            panic!("{MANIFEST_SHA_ENV} must be a lowercase SHA-256");
        }
        println!("cargo:rustc-env={MANIFEST_SHA_ENV}={digest}");
    }
    tauri_build::build()
}
