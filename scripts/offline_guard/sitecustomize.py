"""Bounded Python runtime network monitor for ATLAS verification.

Activated only when ATLAS_OFFLINE_GUARD=1 is set in the environment.
Monitors Python socket/DNS APIs (connect, connect_ex, sendto, sendmsg,
getaddrinfo, gethostbyname, gethostbyname_ex, gethostbyaddr) and Python
subprocess launches that disable sitecustomize (-S / -I) or invoke external
fetchers (curl/wget). Native browser asset traffic is verified separately via
Playwright request interception.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import subprocess
import traceback


def _normalize_host(raw_host: object) -> str:
    if raw_host is None:
        return ""
    if isinstance(raw_host, (bytes, bytearray)):
        host = bytes(raw_host).decode("ascii", errors="ignore").strip().lower()
    else:
        host = str(raw_host).strip().lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if "%" in host:
        host = host.split("%", 1)[0]
    return host


def _is_loopback_or_unspecified_host(raw_host: object) -> bool:
    host = _normalize_host(raw_host)
    if host in {"", "localhost", "localhost."}:
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    if addr.is_loopback or addr.is_unspecified:
        return True
    ipv4_mapped = getattr(addr, "ipv4_mapped", None)
    if ipv4_mapped is not None and (ipv4_mapped.is_loopback or ipv4_mapped.is_unspecified):
        return True
    return False


def _install_offline_guard() -> None:
    if os.environ.get("ATLAS_OFFLINE_GUARD") != "1":
        return

    raw_log = os.environ.get("ATLAS_NET_LOG", "")
    log_path = os.path.abspath(raw_log) if raw_log else ""

    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex
    orig_sendto = socket.socket.sendto
    orig_sendmsg = getattr(socket.socket, "sendmsg", None)
    orig_getaddrinfo = socket.getaddrinfo
    orig_gethostbyname = socket.gethostbyname
    orig_gethostbyname_ex = socket.gethostbyname_ex
    orig_gethostbyaddr = socket.gethostbyaddr
    orig_popen_init = subprocess.Popen.__init__

    def _record_and_block(func_name: str, target: object) -> None:
        record = {
            "pid": os.getpid(),
            "function": func_name,
            "target": repr(target),
            "stack": "".join(traceback.format_stack(limit=8)),
        }
        if log_path:
            try:
                parent = os.path.dirname(log_path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                with open(log_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record) + "\n")
            except OSError:
                pass
        raise OSError(f"ATLAS_OFFLINE_GUARD blocked external network/bypass call via {func_name}: {target!r}")

    def _is_allowed_address(sock: socket.socket, address: object) -> bool:
        af_unix = getattr(socket, "AF_UNIX", None)
        if af_unix is not None and sock.family == af_unix:
            return True
        if isinstance(address, tuple) and len(address) >= 1:
            return _is_loopback_or_unspecified_host(address[0])
        return False

    def guarded_connect(self: socket.socket, address: object) -> object:
        if _is_allowed_address(self, address):
            return orig_connect(self, address)
        _record_and_block("socket.connect", address)

    def guarded_connect_ex(self: socket.socket, address: object) -> int:
        if _is_allowed_address(self, address):
            return orig_connect_ex(self, address)
        _record_and_block("socket.connect_ex", address)
        return 1

    def guarded_sendto(self: socket.socket, data: bytes, *args: object) -> int:
        address = args[-1] if args else None
        if address is None or _is_allowed_address(self, address):
            return orig_sendto(self, data, *args)
        _record_and_block("socket.sendto", address)
        return 0

    def guarded_sendmsg(self: socket.socket, buffers: object, ancdata: object = (), flags: int = 0, address: object = None) -> int:
        if address is None or _is_allowed_address(self, address):
            return orig_sendmsg(self, buffers, ancdata, flags, address)  # type: ignore[misc]
        _record_and_block("socket.sendmsg", address)
        return 0

    def guarded_getaddrinfo(host: object, port: object, *args: object, **kwargs: object) -> object:
        if _is_loopback_or_unspecified_host(host):
            return orig_getaddrinfo(host, port, *args, **kwargs)
        _record_and_block("socket.getaddrinfo", (host, port))

    def guarded_gethostbyname(hostname: object) -> str:
        if _is_loopback_or_unspecified_host(hostname):
            return orig_gethostbyname(hostname)  # type: ignore[arg-type]
        _record_and_block("socket.gethostbyname", hostname)
        return "127.0.0.1"

    def guarded_gethostbyname_ex(hostname: object) -> object:
        if _is_loopback_or_unspecified_host(hostname):
            return orig_gethostbyname_ex(hostname)  # type: ignore[arg-type]
        _record_and_block("socket.gethostbyname_ex", hostname)

    def guarded_gethostbyaddr(ip_address_arg: object) -> object:
        if _is_loopback_or_unspecified_host(ip_address_arg):
            return orig_gethostbyaddr(ip_address_arg)  # type: ignore[arg-type]
        _record_and_block("socket.gethostbyaddr", ip_address_arg)

    def guarded_popen_init(self: subprocess.Popen, args: object, *pargs: object, **kwargs: object) -> None:  # type: ignore[type-arg]
        if kwargs.get("shell"):
            _record_and_block("subprocess.Popen(shell=True)", args)
        argv = [str(a) for a in args] if isinstance(args, (list, tuple)) else [str(args)]
        if argv:
            exe = os.path.basename(argv[0]).lower()
            if exe in {"curl", "wget", "nc", "ncat"}:
                _record_and_block("subprocess.Popen", argv)
            if "python" in exe:
                skip_next = False
                for token in argv[1:]:
                    if skip_next:
                        skip_next = False
                        continue
                    if token in {"-c", "-m"}:
                        break
                    if token in {"-W", "-X", "--check-hash-based-pycs"}:
                        skip_next = True
                        continue
                    if token.startswith("--"):
                        if token in {"--isolated"}:
                            _record_and_block("subprocess.Popen(sitecustomize-bypass)", argv)
                        continue
                    if token.startswith("-") and len(token) > 1:
                        if any(ch in {"S", "I", "E", "s"} for ch in token[1:]):
                            _record_and_block("subprocess.Popen(sitecustomize-bypass)", argv)
                        continue
                    break
        custom_env = kwargs.get("env")
        if isinstance(custom_env, dict):
            guard_dir = os.path.dirname(os.path.abspath(__file__))
            merged_env = dict(custom_env)
            merged_env["ATLAS_OFFLINE_GUARD"] = "1"
            if log_path:
                merged_env["ATLAS_NET_LOG"] = log_path
            existing_pp = merged_env.get("PYTHONPATH", "")
            if guard_dir not in existing_pp.split(os.pathsep):
                merged_env["PYTHONPATH"] = f"{guard_dir}{os.pathsep}{existing_pp}" if existing_pp else guard_dir
            kwargs["env"] = merged_env
        orig_popen_init(self, args, *pargs, **kwargs)

    socket.socket.connect = guarded_connect  # type: ignore[assignment]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[assignment]
    socket.socket.sendto = guarded_sendto  # type: ignore[assignment]
    if orig_sendmsg is not None:
        socket.socket.sendmsg = guarded_sendmsg  # type: ignore[assignment]
    socket.getaddrinfo = guarded_getaddrinfo  # type: ignore[assignment]
    socket.gethostbyname = guarded_gethostbyname  # type: ignore[assignment]
    socket.gethostbyname_ex = guarded_gethostbyname_ex  # type: ignore[assignment]
    socket.gethostbyaddr = guarded_gethostbyaddr  # type: ignore[assignment]
    subprocess.Popen.__init__ = guarded_popen_init  # type: ignore[assignment]


_install_offline_guard()
