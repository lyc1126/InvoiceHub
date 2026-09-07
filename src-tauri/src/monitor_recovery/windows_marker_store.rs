use std::ffi::c_void;
use std::io;
use std::mem::{align_of, offset_of, size_of};
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::IntoRawHandle;
use std::path::Path;
use std::ptr::null_mut;

use windows_sys::Win32::Foundation::{
    CloseHandle, GetLastError, ERROR_ACCESS_DENIED, ERROR_CANT_ACCESS_FILE, ERROR_INVALID_FUNCTION,
    ERROR_INVALID_HANDLE, ERROR_INVALID_REPARSE_DATA, ERROR_NOT_SUPPORTED, HANDLE,
    INVALID_HANDLE_VALUE,
};
use windows_sys::Win32::Storage::FileSystem::{
    FileAttributeTagInfo, FileDispositionInfo, FileStandardInfo, FlushFileBuffers,
    GetFileInformationByHandleEx, GetFileSizeEx, GetFileType, ReadFile, SetFileInformationByHandle,
    WriteFile, FILE_ATTRIBUTE_DEVICE, FILE_ATTRIBUTE_DIRECTORY, FILE_ATTRIBUTE_REPARSE_POINT,
    FILE_ATTRIBUTE_TAG_INFO, FILE_DISPOSITION_INFO, FILE_FLAG_BACKUP_SEMANTICS,
    FILE_FLAG_OPEN_REPARSE_POINT, FILE_GENERIC_READ, FILE_GENERIC_WRITE, FILE_READ_ATTRIBUTES,
    FILE_RENAME_INFO, FILE_SHARE_DELETE, FILE_SHARE_READ, FILE_SHARE_WRITE, FILE_STANDARD_INFO,
    FILE_TYPE_DISK,
};

use super::{MarkerStoreError, RecoveryMarker, RecoveryMarkerStore, RECOVERY_MARKER_FILE};

const MAX_MARKER_BYTES: i64 = 16 * 1024;

// NT relative opens are the Windows equivalent of Unix openat: RootDirectory is
// the already-open directory handle, and ObjectName is only one validated leaf.
type NtStatus = i32;

const OBJ_CASE_INSENSITIVE: u32 = 0x0000_0040;
const FILE_OPEN: u32 = 0x0000_0001;
const FILE_CREATE: u32 = 0x0000_0002;
const FILE_NON_DIRECTORY_FILE: u32 = 0x0000_0040;
const FILE_SYNCHRONOUS_IO_NONALERT: u32 = 0x0000_0020;
const FILE_WRITE_THROUGH: u32 = 0x0000_0002;
const FILE_OPEN_REPARSE_POINT: u32 = 0x0020_0000;
const DELETE_ACCESS: u32 = 0x0001_0000;
const SYNCHRONIZE_ACCESS: u32 = 0x0010_0000;
const FILE_RENAME_INFORMATION_CLASS: u32 = 10;

const STATUS_OBJECT_NAME_NOT_FOUND: NtStatus = 0xC000_0034u32 as NtStatus;
const STATUS_NO_SUCH_FILE: NtStatus = 0xC000_000Fu32 as NtStatus;
const STATUS_OBJECT_NAME_COLLISION: NtStatus = 0xC000_0035u32 as NtStatus;
const STATUS_FILE_IS_A_DIRECTORY: NtStatus = 0xC000_00BAu32 as NtStatus;
const STATUS_NOT_A_DIRECTORY: NtStatus = 0xC000_0103u32 as NtStatus;
const STATUS_OBJECT_TYPE_MISMATCH: NtStatus = 0xC000_0024u32 as NtStatus;
const STATUS_REPARSE_POINT_ENCOUNTERED: NtStatus = 0xC000_050Bu32 as NtStatus;
const STATUS_IO_REPARSE_TAG_NOT_HANDLED: NtStatus = 0xC000_0279u32 as NtStatus;

#[repr(C)]
struct UnicodeString {
    length: u16,
    maximum_length: u16,
    buffer: *mut u16,
}

#[repr(C)]
struct ObjectAttributes {
    length: u32,
    root_directory: HANDLE,
    object_name: *mut UnicodeString,
    attributes: u32,
    security_descriptor: *mut c_void,
    security_quality_of_service: *mut c_void,
}

#[repr(C)]
struct IoStatusBlock {
    status: NtStatus,
    information: usize,
}

#[link(name = "ntdll")]
unsafe extern "system" {
    fn NtCreateFile(
        file_handle: *mut HANDLE,
        desired_access: u32,
        object_attributes: *mut ObjectAttributes,
        io_status_block: *mut IoStatusBlock,
        allocation_size: *mut i64,
        file_attributes: u32,
        share_access: u32,
        create_disposition: u32,
        create_options: u32,
        ea_buffer: *mut c_void,
        ea_length: u32,
    ) -> NtStatus;

    fn NtSetInformationFile(
        file_handle: HANDLE,
        io_status_block: *mut IoStatusBlock,
        file_information: *mut c_void,
        length: u32,
        file_information_class: u32,
    ) -> NtStatus;
}

struct WindowsHandle(HANDLE);

// A Windows HANDLE is process-global, while this wrapper has unique ownership:
// it is neither Clone nor Sync, and its single Drop closes the handle after transfer.
unsafe impl Send for WindowsHandle {}

impl WindowsHandle {
    fn from_raw(raw: HANDLE) -> Result<Self, MarkerStoreError> {
        if raw.is_null() || raw == INVALID_HANDLE_VALUE {
            return Err(MarkerStoreError::StorageUnavailable);
        }
        Ok(Self(raw))
    }

    fn raw(&self) -> HANDLE {
        self.0
    }
}

impl Drop for WindowsHandle {
    fn drop(&mut self) {
        if !self.0.is_null() && self.0 != INVALID_HANDLE_VALUE {
            unsafe {
                CloseHandle(self.0);
            }
        }
    }
}

pub struct WindowsRecoveryMarkerStore {
    directory: WindowsHandle,
}

impl WindowsRecoveryMarkerStore {
    pub fn open(root: &Path) -> Result<Self, MarkerStoreError> {
        if !root.is_absolute() {
            return Err(MarkerStoreError::UnsafeRoot);
        }

        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
            .open(root)
            .map_err(root_open_error)?;
        let raw = file.into_raw_handle() as HANDLE;
        let directory = WindowsHandle::from_raw(raw)?;
        validate_directory(&directory)?;
        Ok(Self { directory })
    }

    fn open_leaf(
        &self,
        name: &str,
        desired_access: u32,
        share_access: u32,
        disposition: u32,
        options: u32,
    ) -> Result<WindowsHandle, NtStatus> {
        let (buffer, mut object_name) =
            relative_name(name).map_err(|_| STATUS_OBJECT_TYPE_MISMATCH)?;
        let mut attributes = ObjectAttributes {
            length: size_of::<ObjectAttributes>() as u32,
            root_directory: self.directory.raw(),
            object_name: &mut object_name,
            attributes: OBJ_CASE_INSENSITIVE,
            security_descriptor: null_mut(),
            security_quality_of_service: null_mut(),
        };
        let mut handle = null_mut();
        let mut io_status = IoStatusBlock {
            status: 0,
            information: 0,
        };
        let status = unsafe {
            NtCreateFile(
                &mut handle,
                desired_access,
                &mut attributes,
                &mut io_status,
                null_mut(),
                0,
                share_access,
                disposition,
                options,
                null_mut(),
                0,
            )
        };
        drop(buffer);
        if status < 0 {
            return Err(status);
        }
        WindowsHandle::from_raw(handle).map_err(|_| STATUS_OBJECT_TYPE_MISMATCH)
    }

    fn open_marker(&self) -> Result<Option<WindowsHandle>, MarkerStoreError> {
        let handle = match self.open_leaf(
            RECOVERY_MARKER_FILE,
            FILE_GENERIC_READ | DELETE_ACCESS | SYNCHRONIZE_ACCESS,
            FILE_SHARE_READ | FILE_SHARE_DELETE,
            FILE_OPEN,
            FILE_NON_DIRECTORY_FILE | FILE_SYNCHRONOUS_IO_NONALERT | FILE_OPEN_REPARSE_POINT,
        ) {
            Ok(handle) => handle,
            Err(status)
                if status == STATUS_OBJECT_NAME_NOT_FOUND || status == STATUS_NO_SUCH_FILE =>
            {
                return Ok(None);
            }
            Err(status) => return Err(open_marker_error(status)),
        };
        validate_regular(&handle)?;
        Ok(Some(handle))
    }

    fn read_handle(&self, handle: &WindowsHandle) -> Result<Vec<u8>, MarkerStoreError> {
        let mut size = 0_i64;
        if unsafe { GetFileSizeEx(handle.raw(), &mut size) } == 0 || size < 0 {
            return Err(MarkerStoreError::StorageUnavailable);
        }
        if size > MAX_MARKER_BYTES {
            return Err(MarkerStoreError::CorruptMarker);
        }
        let mut bytes = vec![0_u8; size as usize];
        let mut offset = 0_usize;
        while offset < bytes.len() {
            let request = (bytes.len() - offset).min(4096) as u32;
            let mut read = 0_u32;
            let ok = unsafe {
                ReadFile(
                    handle.raw(),
                    bytes[offset..].as_mut_ptr(),
                    request,
                    &mut read,
                    null_mut(),
                )
            };
            if ok == 0 {
                return Err(MarkerStoreError::StorageUnavailable);
            }
            if read == 0 {
                return Err(MarkerStoreError::CorruptMarker);
            }
            offset += read as usize;
        }
        Ok(bytes)
    }

    fn write_handle(&self, handle: &WindowsHandle, bytes: &[u8]) -> Result<(), MarkerStoreError> {
        let mut offset = 0_usize;
        while offset < bytes.len() {
            let request = (bytes.len() - offset).min(4096) as u32;
            let mut written = 0_u32;
            let ok = unsafe {
                WriteFile(
                    handle.raw(),
                    bytes[offset..].as_ptr(),
                    request,
                    &mut written,
                    null_mut(),
                )
            };
            if ok == 0 || written == 0 {
                return Err(MarkerStoreError::StorageUnavailable);
            }
            offset += written as usize;
        }
        Ok(())
    }

    fn flush_handle(&self, handle: &WindowsHandle) -> Result<(), MarkerStoreError> {
        if unsafe { FlushFileBuffers(handle.raw()) } == 0 {
            Err(MarkerStoreError::StorageUnavailable)
        } else {
            Ok(())
        }
    }

    fn directory_flush_is_best_effort(error: u32) -> bool {
        matches!(
            error,
            ERROR_INVALID_HANDLE | ERROR_INVALID_FUNCTION | ERROR_NOT_SUPPORTED
        )
    }

    fn flush_directory(&self) -> Result<(), MarkerStoreError> {
        if unsafe { FlushFileBuffers(self.directory.raw()) } != 0 {
            return Ok(());
        }
        // Windows does not promise that a directory handle supports
        // FlushFileBuffers. The marker file itself is flushed with
        // FILE_WRITE_THROUGH before and after the atomic rename. Only the
        // documented unsupported directory-handle errors are best effort;
        // access denied and all other errors remain storage failures.
        if Self::directory_flush_is_best_effort(unsafe { GetLastError() }) {
            Ok(())
        } else {
            Err(MarkerStoreError::StorageUnavailable)
        }
    }

    fn delete_exact(&self, handle: &WindowsHandle) -> Result<(), MarkerStoreError> {
        let disposition = FILE_DISPOSITION_INFO { DeleteFile: true };
        if unsafe {
            SetFileInformationByHandle(
                handle.raw(),
                FileDispositionInfo,
                &disposition as *const _ as *const c_void,
                size_of::<FILE_DISPOSITION_INFO>() as u32,
            )
        } == 0
        {
            Err(MarkerStoreError::StorageUnavailable)
        } else {
            Ok(())
        }
    }

    fn rename_no_replace(
        &self,
        handle: &WindowsHandle,
        destination: &str,
    ) -> Result<(), MarkerStoreError> {
        let (name, object_name) = relative_name(destination)?;
        if align_of::<FILE_RENAME_INFO>() > align_of::<usize>() {
            return Err(MarkerStoreError::InvalidEntry);
        }
        // UNICODE_STRING::length excludes the storage's trailing NUL. Native rename
        // information receives only that validated relative-name extent.
        let name_bytes = usize::from(object_name.length);
        let name_words = name_bytes / size_of::<u16>();
        let header_size = offset_of!(FILE_RENAME_INFO, FileName);
        if header_size >= size_of::<FILE_RENAME_INFO>() {
            return Err(MarkerStoreError::InvalidEntry);
        }
        let byte_len = size_of::<FILE_RENAME_INFO>()
            .checked_add(name_bytes)
            .ok_or(MarkerStoreError::InvalidEntry)?;
        let byte_len_u32 = u32::try_from(byte_len).map_err(|_| MarkerStoreError::InvalidEntry)?;
        let word_count = byte_len
            .checked_add(size_of::<usize>() - 1)
            .ok_or(MarkerStoreError::InvalidEntry)?
            / size_of::<usize>();
        let mut storage = vec![0_usize; word_count];
        // Vec<usize> provides an alignment at least as strict as the Windows
        // struct on supported targets; byte_len remains the exact FFI extent.
        let info = storage.as_mut_ptr().cast::<FILE_RENAME_INFO>();
        unsafe {
            (*info).Anonymous.ReplaceIfExists = false;
            (*info).RootDirectory = self.directory.raw();
            (*info).FileNameLength = name_bytes as u32;
            std::ptr::copy_nonoverlapping(name.as_ptr(), (*info).FileName.as_mut_ptr(), name_words);
            let mut io_status = IoStatusBlock {
                status: 0,
                information: 0,
            };
            // SetFileInformationByHandle rejects a non-null RootDirectory with
            // ERROR_INVALID_PARAMETER. NtSetInformationFile preserves the pinned
            // directory handle, so the destination cannot be redirected through a
            // path re-resolution between validation and the no-replace rename.
            let status = NtSetInformationFile(
                handle.raw(),
                &mut io_status,
                info.cast::<c_void>(),
                byte_len_u32,
                FILE_RENAME_INFORMATION_CLASS,
            );
            if status < 0 {
                if status == STATUS_OBJECT_NAME_COLLISION {
                    return Err(MarkerStoreError::MarkerChanged);
                }
                return Err(MarkerStoreError::StorageUnavailable);
            }
        }
        Ok(())
    }
}

impl RecoveryMarkerStore for WindowsRecoveryMarkerStore {
    fn load(&mut self) -> Result<Option<RecoveryMarker>, MarkerStoreError> {
        let Some(handle) = self.open_marker()? else {
            return Ok(None);
        };
        let bytes = self.read_handle(&handle)?;
        RecoveryMarker::decode(&bytes).map(Some)
    }

    fn publish(&mut self, marker: &RecoveryMarker) -> Result<(), MarkerStoreError> {
        let bytes = marker.encode()?;
        // A preflight handle makes an existing marker (including a corrupt
        // regular marker) an explicit no-clobber failure. The atomic rename
        // below remains the final authority if a creator races this check.
        if self.open_marker()?.is_some() {
            return Err(MarkerStoreError::MarkerChanged);
        }
        let temporary_name = format!(
            ".{RECOVERY_MARKER_FILE}.pending.{}",
            super::random_hex_16()?
        );
        let temporary = match self.open_leaf(
            &temporary_name,
            // The new handle is validated before writing. Without read-attributes
            // access, a valid temporary marker fails the no-reparse check as storage unavailable.
            FILE_GENERIC_WRITE | FILE_READ_ATTRIBUTES | DELETE_ACCESS | SYNCHRONIZE_ACCESS,
            FILE_SHARE_READ | FILE_SHARE_DELETE,
            FILE_CREATE,
            FILE_NON_DIRECTORY_FILE
                | FILE_SYNCHRONOUS_IO_NONALERT
                | FILE_WRITE_THROUGH
                | FILE_OPEN_REPARSE_POINT,
        ) {
            Ok(handle) => handle,
            Err(_) => return Err(MarkerStoreError::StorageUnavailable),
        };
        validate_regular(&temporary)?;
        if let Err(error) = self.write_handle(&temporary, &bytes) {
            let _ = self.delete_exact(&temporary);
            return Err(error);
        }
        if let Err(error) = self.flush_handle(&temporary) {
            let _ = self.delete_exact(&temporary);
            return Err(error);
        }
        if let Err(error) = self.rename_no_replace(&temporary, RECOVERY_MARKER_FILE) {
            let _ = self.delete_exact(&temporary);
            return Err(error);
        }
        // The handle now names the final marker. A second flush keeps the
        // crash-recovery record durable after the atomic metadata update.
        self.flush_handle(&temporary)?;
        drop(temporary);
        self.flush_directory()?;
        match self.load()? {
            Some(written) if written == *marker => Ok(()),
            _ => Err(MarkerStoreError::MarkerChanged),
        }
    }

    fn clear(&mut self, expected: &RecoveryMarker) -> Result<(), MarkerStoreError> {
        let Some(handle) = self.open_marker()? else {
            return Err(MarkerStoreError::MarkerChanged);
        };
        let bytes = self.read_handle(&handle)?;
        let current = RecoveryMarker::decode(&bytes)?;
        if current != *expected {
            return Err(MarkerStoreError::MarkerChanged);
        }
        // Delete disposition applies to this opened file object, not to a
        // name that an attacker can replace after the comparison.
        self.delete_exact(&handle)?;
        drop(handle);
        self.flush_directory()
    }
}

fn relative_name(name: &str) -> Result<(Vec<u16>, UnicodeString), MarkerStoreError> {
    if name.is_empty()
        || name == "."
        || name == ".."
        || name.chars().any(|character| {
            character == '\\' || character == '/' || character == ':' || character == '\0'
        })
    {
        return Err(MarkerStoreError::InvalidEntry);
    }
    let mut buffer: Vec<u16> = name.encode_utf16().collect();
    if buffer.len() > (u16::MAX as usize / 2).saturating_sub(1) {
        return Err(MarkerStoreError::InvalidEntry);
    }
    let length = (buffer.len() * size_of::<u16>()) as u16;
    buffer.push(0);
    let object_name = UnicodeString {
        length,
        maximum_length: (buffer.len() * size_of::<u16>()) as u16,
        buffer: buffer.as_mut_ptr(),
    };
    Ok((buffer, object_name))
}

fn validate_directory(handle: &WindowsHandle) -> Result<(), MarkerStoreError> {
    let mut attributes = FILE_ATTRIBUTE_TAG_INFO::default();
    if unsafe {
        GetFileInformationByHandleEx(
            handle.raw(),
            FileAttributeTagInfo,
            &mut attributes as *mut _ as *mut c_void,
            size_of::<FILE_ATTRIBUTE_TAG_INFO>() as u32,
        )
    } == 0
    {
        return Err(MarkerStoreError::UnsafeRoot);
    }
    if attributes.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
        || attributes.FileAttributes & FILE_ATTRIBUTE_DEVICE != 0
        || attributes.FileAttributes & FILE_ATTRIBUTE_DIRECTORY == 0
        || unsafe { GetFileType(handle.raw()) } != FILE_TYPE_DISK
    {
        return Err(MarkerStoreError::UnsafeRoot);
    }
    Ok(())
}

fn validate_regular(handle: &WindowsHandle) -> Result<(), MarkerStoreError> {
    let mut attributes = FILE_ATTRIBUTE_TAG_INFO::default();
    if unsafe {
        GetFileInformationByHandleEx(
            handle.raw(),
            FileAttributeTagInfo,
            &mut attributes as *mut _ as *mut c_void,
            size_of::<FILE_ATTRIBUTE_TAG_INFO>() as u32,
        )
    } == 0
    {
        return Err(MarkerStoreError::StorageUnavailable);
    }
    if attributes.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
        return Err(MarkerStoreError::SymlinkRejected);
    }
    if attributes.FileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_DEVICE) != 0
        || unsafe { GetFileType(handle.raw()) } != FILE_TYPE_DISK
    {
        return Err(MarkerStoreError::InvalidEntry);
    }
    let mut standard = FILE_STANDARD_INFO::default();
    if unsafe {
        GetFileInformationByHandleEx(
            handle.raw(),
            FileStandardInfo,
            &mut standard as *mut _ as *mut c_void,
            size_of::<FILE_STANDARD_INFO>() as u32,
        )
    } == 0
    {
        return Err(MarkerStoreError::StorageUnavailable);
    }
    if standard.Directory {
        return Err(MarkerStoreError::InvalidEntry);
    }
    Ok(())
}

fn root_open_error(error: io::Error) -> MarkerStoreError {
    match error.raw_os_error().map(|value| value as u32) {
        Some(ERROR_CANT_ACCESS_FILE) | Some(ERROR_INVALID_REPARSE_DATA) => {
            MarkerStoreError::SymlinkRejected
        }
        Some(ERROR_ACCESS_DENIED) => MarkerStoreError::UnsafeRoot,
        _ => MarkerStoreError::UnsafeRoot,
    }
}

fn open_marker_error(status: NtStatus) -> MarkerStoreError {
    match status {
        STATUS_OBJECT_NAME_COLLISION => MarkerStoreError::MarkerChanged,
        STATUS_REPARSE_POINT_ENCOUNTERED | STATUS_IO_REPARSE_TAG_NOT_HANDLED => {
            MarkerStoreError::SymlinkRejected
        }
        STATUS_FILE_IS_A_DIRECTORY | STATUS_NOT_A_DIRECTORY | STATUS_OBJECT_TYPE_MISMATCH => {
            MarkerStoreError::InvalidEntry
        }
        _ => MarkerStoreError::StorageUnavailable,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn directory_flush_only_ignores_unsupported_handle_errors() {
        assert!(WindowsRecoveryMarkerStore::directory_flush_is_best_effort(
            ERROR_INVALID_HANDLE
        ));
        assert!(WindowsRecoveryMarkerStore::directory_flush_is_best_effort(
            ERROR_INVALID_FUNCTION
        ));
        assert!(WindowsRecoveryMarkerStore::directory_flush_is_best_effort(
            ERROR_NOT_SUPPORTED
        ));
        assert!(!WindowsRecoveryMarkerStore::directory_flush_is_best_effort(
            ERROR_ACCESS_DENIED
        ));
    }

    #[test]
    fn rename_info_backing_alignment_and_header_are_representable() {
        assert!(align_of::<FILE_RENAME_INFO>() <= align_of::<usize>());
        assert!(offset_of!(FILE_RENAME_INFO, FileName) < size_of::<FILE_RENAME_INFO>());
    }
}
