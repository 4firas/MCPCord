"""OS credential stores only. Never accept a token through args, config or environment."""
import ctypes
import getpass
import shutil
import subprocess
import sys
import warnings

from .reader import ReaderError

# Retained for compatibility with the first local release; these names are not secrets.
SERVICE = "local.codex.discord-export-reader"
ACCOUNT = "personal-discord-readonly"
WINDOWS_TARGET = "MCPCord/Discord"


def validate_secret(value):
    if not isinstance(value, str) or not value or len(value) > 2048 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise ReaderError("The local credential value is invalid; no request was sent.")
    return value


def secret_tool():
    executable = shutil.which("secret-tool")
    if executable is None:
        raise ReaderError("Linux needs secret-tool (libsecret tools) and an unlocked desktop keyring.")
    return executable


def provider_name():
    if sys.platform == "darwin":
        return "macOS Keychain"
    if sys.platform == "win32":
        return "Windows Credential Manager"
    if sys.platform.startswith("linux"):
        if shutil.which("secret-tool") is None:
            raise ReaderError("Linux needs secret-tool (libsecret tools) and an unlocked Secret Service desktop session.")
        return "Linux Secret Service"
    raise ReaderError("Credential setup supports macOS, Windows and Linux desktop sessions.")


def _windows_api():
    from ctypes import wintypes

    class Credential(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(wintypes.BYTE)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
                    ("Attributes", wintypes.LPVOID), ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]
    api = getattr(ctypes, "WinDLL")("Advapi32.dll", use_last_error=True)  # noqa: B009 - WinDLL exists only on Windows
    pointer = ctypes.POINTER(Credential)
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(pointer)]
    api.CredReadW.restype = wintypes.BOOL
    api.CredWriteW.argtypes = [pointer, wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    api.CredFree.argtypes = [wintypes.LPVOID]
    return api, Credential


def _windows_read():
    api, credential_type = _windows_api()
    pointer = ctypes.POINTER(credential_type)()
    if not api.CredReadW(WINDOWS_TARGET, 1, 0, ctypes.byref(pointer)):
        raise ReaderError("MCPCord's Windows credential is unavailable. Run mcpcord auth locally.")
    try:
        credential = pointer.contents
        if credential.CredentialBlobSize > 2048:
            raise ReaderError("Stored credential exceeds the size limit.")
        return ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize).decode("utf-8")
    finally:
        api.CredFree(pointer)


def _windows_write(value):
    from ctypes import wintypes
    api, credential_type = _windows_api()
    blob = ctypes.create_string_buffer(value.encode("utf-8"))
    credential = credential_type()
    credential.Type = 1  # CRED_TYPE_GENERIC
    credential.TargetName = WINDOWS_TARGET
    credential.UserName = "discord-readonly"
    credential.Comment = "MCPCord local Discord credential"
    credential.CredentialBlobSize = len(value.encode("utf-8"))
    credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(wintypes.BYTE))
    credential.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE, scoped to the current Windows user
    if not api.CredWriteW(ctypes.byref(credential), 0):
        raise ReaderError("Windows could not save the dedicated MCPCord credential.")


def read_credential():
    try:
        provider_name()
        if sys.platform == "win32":
            return validate_secret(_windows_read())
        command = (["/usr/bin/security", "find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"]
                   if sys.platform == "darwin" else [secret_tool(), "lookup", "service", SERVICE, "account", ACCOUNT])
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=False)
        if result.returncode:
            raise ReaderError("Dedicated credential unavailable. Run mcpcord auth locally; no request was sent.")
        return validate_secret(result.stdout.decode("utf-8").rstrip("\n"))
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise ReaderError("Local credential lookup failed; no secret or raw error was logged.") from None


def store_credential(replace=False):
    provider = provider_name()
    if not sys.stdin.isatty():
        raise ReaderError("Run credential setup in your own interactive terminal. Piped token input is not accepted.")
    if sys.platform == "darwin":
        command = ["/usr/bin/security", "add-generic-password", "-a", ACCOUNT, "-s", SERVICE, "-l", "MCPCord", "-T", ""]
        if replace:
            command.append("-U")
        command.append("-w")  # Last, without a value: security itself opens the non-echoing prompt.
        try:
            result = subprocess.run(command, check=False)
        except OSError:
            raise ReaderError("macOS credential setup could not start.") from None
        if result.returncode:
            raise ReaderError("Keychain setup did not complete. Use mcpcord auth --replace if replacing this app's existing item.")
    else:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                value = validate_secret(getpass.getpass("Discord token (hidden, stays on this computer): "))
            if sys.platform == "win32":
                _windows_write(value)
            else:
                result = subprocess.run([secret_tool(), "store", "--label=MCPCord", "service", SERVICE, "account", ACCOUNT],
                                        input=value.encode(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
                if result.returncode:
                    raise ReaderError("Secret Service could not save the dedicated MCPCord item.")
        except (OSError, subprocess.SubprocessError, getpass.GetPassWarning, EOFError):
            raise ReaderError("Secure credential entry failed; no token was logged.") from None
    return provider
