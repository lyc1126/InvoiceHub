"""Native, recycle-only removal. There is deliberately no unlink fallback."""
from __future__ import annotations

import ctypes as c
import sys
import uuid
from pathlib import Path


def recycle_guard(flags: int) -> int:
    # IFileOperation may propose permanent deletion when a volume/bin cannot recycle.
    # Refuse that transfer before it starts, even though RECYCLEONDELETE was requested.
    return 0 if flags & 0x80 else -2147467259  # TSF_DELETE_RECYCLE_IF_POSSIBLE / E_FAIL


def move_to_trash(path: Path) -> None:
    if sys.platform == "darwin":
        _mac_trash(path)
    elif sys.platform == "win32":
        _windows_trash(path)
    else:
        raise OSError("当前系统不支持安全移入废纸篓；文件未删除。")


def _mac_trash(path: Path) -> Path | None:
    c.CDLL("/System/Library/Frameworks/Foundation.framework/Foundation")
    objc = c.CDLL("/usr/lib/libobjc.A.dylib")
    objc.objc_getClass.argtypes = [c.c_char_p]
    objc.objc_getClass.restype = c.c_void_p
    objc.sel_registerName.argtypes = [c.c_char_p]
    objc.sel_registerName.restype = c.c_void_p

    def send(receiver, name, result=c.c_void_p, types=(), args=()):
        call = c.CFUNCTYPE(result, c.c_void_p, c.c_void_p, *types)(("objc_msgSend", objc))
        return call(receiver, objc.sel_registerName(name), *args)

    pool = send(send(objc.objc_getClass(b"NSAutoreleasePool"), b"alloc"), b"init")
    try:
        string = send(objc.objc_getClass(b"NSString"), b"stringWithUTF8String:",
                      types=(c.c_char_p,), args=(str(path).encode("utf-8"),))
        url = send(objc.objc_getClass(b"NSURL"), b"fileURLWithPath:", types=(c.c_void_p,), args=(string,))
        manager = send(objc.objc_getClass(b"NSFileManager"), b"defaultManager")
        error, destination = c.c_void_p(), c.c_void_p()
        ok = send(manager, b"trashItemAtURL:resultingItemURL:error:", c.c_bool,
                  (c.c_void_p, c.POINTER(c.c_void_p), c.POINTER(c.c_void_p)),
                  (url, c.byref(destination), c.byref(error)))
        if not ok:
            raise OSError("系统未能将文件移入废纸篓，请检查文件权限和所在磁盘。")
        if destination.value:
            destination_path = send(destination.value, b"path")
            text = send(destination_path, b"UTF8String", c.c_char_p)
            return Path(text.decode("utf-8")) if text else None
        return None
    finally:
        send(pool, b"drain", None)


def _windows_trash(path: Path) -> None:
    # Fixed Win32 COM ABI; callbacks and vtable stay alive until all COM references
    # are released. No PowerShell, external command, or extra packaged dependency.
    ptr, hr, dword = c.c_void_p, c.c_int32, c.c_uint32
    guid_type = c.c_ubyte * 16
    guid = lambda value: guid_type.from_buffer_copy(uuid.UUID(value).bytes_le)
    iid_sink = guid("04b0f1a7-9490-44bc-96e1-4296a31252e2")
    iid_unknown = guid("00000000-0000-0000-c000-000000000046")
    ole = c.OleDLL("ole32")
    shell = c.OleDLL("shell32")
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    ole.CoInitializeEx.argtypes = [ptr, dword]
    ole.CoInitializeEx.restype = hr
    ole.CoCreateInstance.argtypes = [ptr, ptr, dword, ptr, c.POINTER(ptr)]
    ole.CoCreateInstance.restype = hr
    shell.SHCreateItemFromParsingName.argtypes = [c.c_wchar_p, ptr, ptr, c.POINTER(ptr)]
    shell.SHCreateItemFromParsingName.restype = hr

    def checked(code):
        if code < 0:
            raise OSError(f"系统回收站操作失败（0x{code & 0xffffffff:08X}），未执行永久删除。")

    def invoke(obj, index, types=(), args=()):
        table = c.cast(obj, c.POINTER(c.POINTER(ptr))).contents
        return c.WINFUNCTYPE(hr, ptr, *types)(table[index])(obj, *args)

    refs = [1]
    observed = {"recycled": False, "result": None, "destination": False}

    def query(this, requested, output):
        if c.string_at(requested, 16) not in (bytes(iid_sink), bytes(iid_unknown)):
            output[0] = None
            return -2147467262
        output[0] = this
        refs[0] += 1
        return 0

    def add_ref(this):
        refs[0] += 1
        return refs[0]

    def release(this):
        refs[0] -= 1
        return refs[0]

    def pre_delete(this, flags, item):
        code = recycle_guard(flags)
        observed["recycled"] = code == 0
        return code

    def post_delete(this, flags, item, result, created):
        observed["result"] = result
        # PostDeleteItem supplies a shell item only when the source reached the
        # Recycle Bin. A successful HRESULT alone must not claim recoverability.
        observed["destination"] = bool(created)
        return 0

    noop = lambda *args: 0
    signatures = [
        (hr, (ptr, c.POINTER(ptr)), query), (dword, (), add_ref), (dword, (), release),
        (hr, (), noop), (hr, (hr,), noop),
        (hr, (dword, ptr, ptr), noop), (hr, (dword, ptr, ptr, hr, ptr), noop),
        (hr, (dword, ptr, ptr, ptr), noop), (hr, (dword, ptr, ptr, ptr, hr, ptr), noop),
        (hr, (dword, ptr, ptr, ptr), noop), (hr, (dword, ptr, ptr, ptr, hr, ptr), noop),
        (hr, (dword, ptr), pre_delete), (hr, (dword, ptr, hr, ptr), post_delete),
        (hr, (dword, ptr, ptr), noop), (hr, (dword, ptr, ptr, ptr, dword, hr, ptr), noop),
        (hr, (dword, dword), noop), (hr, (), noop), (hr, (), noop), (hr, (), noop),
    ]
    callbacks = [c.WINFUNCTYPE(result, ptr, *types)(fn) for result, types, fn in signatures]
    table = (ptr * len(callbacks))(*(c.cast(fn, ptr).value for fn in callbacks))
    sink = c.pointer(c.cast(table, ptr))
    operation, item = ptr(), ptr()
    checked(ole.CoInitializeEx(None, 2))
    try:
        checked(ole.CoCreateInstance(guid("3ad05575-8857-4850-9277-11b85bdb8e09"), None, 1,
                                     guid("947aab5f-0a5c-4c13-b4d6-4bf7836fc9f8"), c.byref(operation)))
        checked(shell.SHCreateItemFromParsingName(str(path), None,
                    guid("43826d1e-e718-42ee-bc55-a1e261c37bfe"), c.byref(item)))
        flags = 0x20000000 | 0x80000 | 0x100000 | 0x400 | 0x10 | 0x4
        checked(invoke(operation, 5, (dword,), (flags,)))
        checked(invoke(operation, 18, (ptr, ptr), (item, c.cast(sink, ptr))))
        checked(invoke(operation, 21))
        aborted = c.c_int()
        checked(invoke(operation, 22, (c.POINTER(c.c_int),), (c.byref(aborted),)))
        if aborted.value or not observed["recycled"] or observed["result"] is None:
            raise OSError("系统未确认文件已进入回收站；操作已停止，请核对源目录和回收站。")
        checked(observed["result"])
        if not observed["destination"]:
            raise OSError("系统未返回回收站中的文件；操作已停止，请核对源目录和回收站。")
    finally:
        if item:
            invoke(item, 2)
        if operation:
            invoke(operation, 2)
        ole.CoUninitialize()
