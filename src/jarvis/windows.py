"""Win32 file handles and private ACLs; imported lazily on Windows only."""

from __future__ import annotations

import contextlib
import ctypes as c
import os
from ctypes import wintypes as w
from functools import cache
from pathlib import Path


@cache
def api():
    if os.name != "nt":
        raise RuntimeError("Win32 operations require Windows.")
    kernel = c.WinDLL("kernel32", use_last_error=True)
    security = c.WinDLL("advapi32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        w.LPCWSTR,
        w.DWORD,
        w.DWORD,
        c.c_void_p,
        w.DWORD,
        w.DWORD,
        w.HANDLE,
    ]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    kernel.GetFileInformationByHandle.argtypes = [w.HANDLE, c.c_void_p]
    kernel.GetFileInformationByHandle.restype = w.BOOL
    kernel.GetFileType.argtypes = [w.HANDLE]
    kernel.GetFileType.restype = w.DWORD
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.GetSystemDirectoryW.argtypes = [w.LPWSTR, w.UINT]
    kernel.GetSystemDirectoryW.restype = w.UINT
    kernel.ReplaceFileW.argtypes = [
        w.LPCWSTR,
        w.LPCWSTR,
        w.LPCWSTR,
        w.DWORD,
        c.c_void_p,
        c.c_void_p,
    ]
    kernel.ReplaceFileW.restype = w.BOOL
    kernel.LocalFree.argtypes = [c.c_void_p]
    kernel.LocalFree.restype = c.c_void_p
    security.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]
    security.OpenProcessToken.restype = w.BOOL
    security.GetTokenInformation.argtypes = [
        w.HANDLE,
        c.c_int,
        c.c_void_p,
        w.DWORD,
        c.POINTER(w.DWORD),
    ]
    security.GetTokenInformation.restype = w.BOOL
    security.ConvertSidToStringSidW.argtypes = [c.c_void_p, c.POINTER(w.LPWSTR)]
    security.ConvertSidToStringSidW.restype = w.BOOL
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        w.LPCWSTR,
        w.DWORD,
        c.POINTER(c.c_void_p),
        c.c_void_p,
    ]
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = w.BOOL
    security.GetSecurityDescriptorDacl.argtypes = [
        c.c_void_p,
        c.POINTER(w.BOOL),
        c.POINTER(c.c_void_p),
        c.POINTER(w.BOOL),
    ]
    security.GetSecurityDescriptorDacl.restype = w.BOOL
    security.SetNamedSecurityInfoW.argtypes = [
        w.LPWSTR,
        c.c_int,
        w.DWORD,
        c.c_void_p,
        c.c_void_p,
        c.c_void_p,
        c.c_void_p,
    ]
    security.SetNamedSecurityInfoW.restype = w.DWORD
    return kernel, security


@cache
def user_sid() -> str:
    kernel, security = api()
    token = w.HANDLE()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, c.byref(token)):
        raise c.WinError(c.get_last_error())
    try:
        needed = w.DWORD()
        security.GetTokenInformation(token, 1, None, 0, c.byref(needed))
        buffer = c.create_string_buffer(needed.value)
        if not security.GetTokenInformation(token, 1, buffer, needed, c.byref(needed)):
            raise c.WinError(c.get_last_error())
        sid = c.cast(buffer, c.POINTER(c.c_void_p))[0]
        text = w.LPWSTR()
        if not security.ConvertSidToStringSidW(sid, c.byref(text)):
            raise c.WinError(c.get_last_error())
        try:
            return text.value
        finally:
            kernel.LocalFree(text)
    finally:
        kernel.CloseHandle(token)


def protect_path(path: Path, *, directory=False):
    kernel, security = api()
    inherit = "OICI" if directory else ""
    sddl = "D:P" + "".join(f"(A;{inherit};FA;;;{sid})" for sid in (user_sid(), "SY", "BA"))
    descriptor = c.c_void_p()
    if not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, 1, c.byref(descriptor), None
    ):
        raise c.WinError(c.get_last_error())
    try:
        present, defaulted, dacl = w.BOOL(), w.BOOL(), c.c_void_p()
        if (
            not security.GetSecurityDescriptorDacl(
                descriptor, c.byref(present), c.byref(dacl), c.byref(defaulted)
            )
            or not present.value
        ):
            raise PermissionError("Could not construct Jarvis's private Windows ACL.")
        code = security.SetNamedSecurityInfoW(str(path), 1, 0x80000004, None, None, dacl, None)
        if code:
            raise PermissionError(
                f"Could not protect Jarvis data with a private Windows ACL (error {code})."
            )
    finally:
        kernel.LocalFree(descriptor)


class FileInfo(c.Structure):
    _fields_ = [
        ("attributes", w.DWORD),
        ("created", w.FILETIME),
        ("accessed", w.FILETIME),
        ("modified", w.FILETIME),
        ("volume", w.DWORD),
        ("size_high", w.DWORD),
        ("size_low", w.DWORD),
        ("links", w.DWORD),
        ("index_high", w.DWORD),
        ("index_low", w.DWORD),
    ]


def open_handle(path: Path, *, directory=False) -> int:
    kernel, _ = api()
    # Do not follow reparse points; deny rename/delete while this handle is held.
    handle = kernel.CreateFileW(
        str(path),
        0x80 if directory else 0x80000000,
        3 if directory else 1,
        None,
        3,
        0x00200000 | (0x02000000 if directory else 0),
        None,
    )
    if handle == c.c_void_p(-1).value:
        raise c.WinError(c.get_last_error())
    try:
        info = FileInfo()
        if not kernel.GetFileInformationByHandle(handle, c.byref(info)):
            raise c.WinError(c.get_last_error())
        if info.attributes & 0x400 or bool(info.attributes & 0x10) != directory:
            raise PermissionError(
                "Workspace reparse points and unexpected file types are not allowed."
            )
        if not directory and (
            kernel.GetFileType(handle) != 1
            or info.size_high
            or info.size_low > 256000
            or info.links > 1
        ):
            raise ValueError("A regular, unlinked text file up to 256 KB is required.")
        return handle
    except BaseException:
        kernel.CloseHandle(handle)
        raise


@contextlib.contextmanager
def locked_directory(path: Path):
    if path.anchor.startswith("\\\\"):
        raise PermissionError("Windows workspace tools require a local drive.")
    kernel, _ = api()
    handles = []
    try:
        for directory in [*reversed(path.parents), path]:
            handles.append(open_handle(directory, directory=True))
        yield
    finally:
        for handle in reversed(handles):
            kernel.CloseHandle(handle)


def read_text(path: Path) -> str:
    import msvcrt

    with locked_directory(path.parent):
        handle = open_handle(path)
        try:
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            api()[0].CloseHandle(handle)
            raise
        with os.fdopen(fd, "r", encoding="utf-8") as file:
            return file.read(256001)


def system_executable(name: str) -> str:
    kernel, _ = api()
    buffer = c.create_unicode_buffer(32768)
    count = kernel.GetSystemDirectoryW(buffer, len(buffer))
    if not count or count >= len(buffer):
        raise RuntimeError("The Windows system directory is unavailable.")
    return str(Path(buffer.value) / name)


def replace_file(source: Path, target: Path):
    if target.exists():
        # ReplaceFile preserves the destination's ACL instead of broadening it
        # to the temporary file's inherited permissions.
        if not api()[0].ReplaceFileW(str(target), str(source), None, 0, None, None):
            raise c.WinError(c.get_last_error())
    else:
        os.replace(source, target)
