use std::fs;
use std::path::PathBuf;

fn windows_marker_store_source() -> String {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("src")
        .join("monitor_recovery")
        .join("windows_marker_store.rs");
    fs::read_to_string(path).expect("Windows marker-store source")
}

#[test]
fn windows_marker_store_contract_is_pinned_and_handle_relative() {
    let windows = windows_marker_store_source();
    let monitor_recovery = fs::read_to_string(
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("src")
            .join("monitor_recovery.rs"),
    )
    .expect("monitor recovery source");
    assert!(monitor_recovery.contains(
        "#[path = \"monitor_recovery/windows_marker_store.rs\"]\nmod windows_marker_store;"
    ));

    for required in [
        "NtCreateFile",
        "root_directory: self.directory.raw()",
        "FILE_OPEN_REPARSE_POINT",
        "FILE_ATTRIBUTE_REPARSE_POINT",
        "SetFileInformationByHandle",
        "NtSetInformationFile",
        "FILE_RENAME_INFORMATION_CLASS",
        "ReplaceIfExists = false",
        "FileDispositionInfo",
        "FlushFileBuffers",
        "directory_flush_is_best_effort",
        "offset_of!(FILE_RENAME_INFO, FileName)",
        "align_of::<FILE_RENAME_INFO>()",
        "vec![0_usize",
        "byte_len_u32",
        "unsafe impl Send for WindowsHandle",
    ] {
        assert!(
            windows.contains(required),
            "missing Windows marker contract: {required}"
        );
    }

    for forbidden in [
        "std::fs::read(",
        "std::fs::write(",
        "std::fs::rename(",
        "std::fs::remove_file(",
        "std::fs::remove_dir(",
    ] {
        assert!(
            !windows.contains(forbidden),
            "Windows marker store used path operation: {forbidden}"
        );
    }

    let rename = windows
        .split("fn rename_no_replace")
        .nth(1)
        .and_then(|body| body.split("impl RecoveryMarkerStore").next())
        .expect("rename implementation");
    for forbidden in [
        "vec![0_u8",
        "size_of::<FILE_RENAME_INFO>() - size_of::<[u16; 1]>()",
        "storage.len() as u32",
        "as *mut FILE_RENAME_INFO",
    ] {
        assert!(
            !rename.contains(forbidden),
            "rename implementation regressed to unsafe layout: {forbidden}"
        );
    }

    let flush = windows
        .split("fn directory_flush_is_best_effort")
        .nth(1)
        .and_then(|body| body.split("fn delete_exact").next())
        .expect("directory flush error policy");
    assert!(flush.contains("ERROR_INVALID_HANDLE"));
    assert!(flush.contains("ERROR_INVALID_FUNCTION"));
    assert!(flush.contains("ERROR_NOT_SUPPORTED"));
    assert!(
        !flush.contains("ERROR_ACCESS_DENIED"),
        "access denied must remain a directory flush failure"
    );

    let publish = windows
        .split("fn publish")
        .nth(1)
        .and_then(|body| body.split("fn clear").next())
        .expect("publish implementation");
    assert!(
        publish.contains(
            "FILE_GENERIC_WRITE | FILE_READ_ATTRIBUTES | DELETE_ACCESS | SYNCHRONIZE_ACCESS"
        ),
        "temporary marker validation must retain read-attributes access"
    );
    assert!(
        rename.contains("let name_bytes = usize::from(object_name.length);"),
        "rename extent must exclude the UTF-16 terminator"
    );
    assert!(
        rename.contains("name_words"),
        "rename copy length must follow the non-terminated UnicodeString extent"
    );
    assert!(
        rename.contains("NtSetInformationFile(")
            && rename.contains("FILE_RENAME_INFORMATION_CLASS"),
        "handle-relative rename must use the native information call"
    );
    assert!(
        !rename.contains("SetFileInformationByHandle("),
        "Win32 rename rejects the pinned RootDirectory handle"
    );
}

#[cfg(windows)]
mod windows_runtime_contracts {
    use super::*;
    use invoicehub_desktop::monitor_recovery::{
        LifecycleLease, LifecyclePhase, MarkerStoreError, RecoveryMarker, RecoveryMarkerStore,
        WindowsRecoveryMarkerStore, RECOVERY_MARKER_FILE,
    };

    fn marker() -> RecoveryMarker {
        RecoveryMarker::new(
            "a".repeat(32),
            LifecycleLease {
                generation: 1,
                phase: LifecyclePhase::OwnedRunning,
                health_pid: 11,
                owned_pid: 11,
                process_pid: 11,
                startup_gate_released: true,
                state_scope: "b".repeat(64),
            },
        )
        .expect("valid marker")
    }

    fn isolated_root(suffix: &str) -> PathBuf {
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        for attempt in 0..32_u32 {
            let root = std::env::temp_dir().join(format!(
                "invoicehub-windows-marker-{}-{stamp}-{attempt}-{suffix}",
                std::process::id()
            ));
            match fs::create_dir(&root) {
                Ok(()) => return root,
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
                Err(error) => panic!("isolated marker root: {error}"),
            }
        }
        panic!("could not allocate a unique isolated marker root");
    }

    #[test]
    fn relative_root_is_rejected_before_open() {
        assert!(matches!(
            WindowsRecoveryMarkerStore::open(PathBuf::from("relative").as_path()),
            Err(MarkerStoreError::UnsafeRoot)
        ));
    }

    #[test]
    fn round_trip_and_exact_clear_are_handle_based() {
        let root = isolated_root("round-trip");
        let mut store = WindowsRecoveryMarkerStore::open(&root).expect("open root");
        let expected = marker();

        store.publish(&expected).expect("publish marker");
        assert_eq!(store.load(), Ok(Some(expected.clone())));
        store.clear(&expected).expect("clear marker");
        assert_eq!(store.load(), Ok(None));

        fs::remove_dir(root).expect("remove isolated root");
    }

    #[test]
    fn existing_marker_is_never_clobbered() {
        let root = isolated_root("no-clobber");
        let mut store = WindowsRecoveryMarkerStore::open(&root).expect("open root");
        let first = marker();
        let second =
            RecoveryMarker::new("c".repeat(32), first.origin_lease.clone()).expect("second marker");

        store.publish(&first).expect("publish first marker");
        assert_eq!(store.publish(&second), Err(MarkerStoreError::MarkerChanged));
        assert_eq!(store.load(), Ok(Some(first)));

        fs::remove_file(root.join(RECOVERY_MARKER_FILE)).expect("remove marker");
        fs::remove_dir(root).expect("remove isolated root");
    }
}
