fn main() {
    let _ = tauri::generate_context!();
    let origin = invoicehub_desktop::backend_origin();
    eprintln!(
        "InvoiceHub Tauri host foundation is not runnable yet. Complete the fixed backend lifecycle and Cargo lock before starting {origin}."
    );
    std::process::exit(78);
}
