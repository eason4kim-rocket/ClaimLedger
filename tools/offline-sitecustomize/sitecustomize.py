"""Test-only network guard: reject every non-loopback socket connection."""

from __future__ import annotations

import ipaddress
import socket


_original_connect = socket.socket.connect
_original_create_connection = socket.create_connection


def _is_loopback(host: object) -> bool:
    value = str(host).strip("[]").lower()
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _guarded_connect(self: socket.socket, address: object) -> object:
    host = address[0] if isinstance(address, tuple) and address else address
    if not _is_loopback(host):
        raise OSError(f"offline validation blocked non-loopback connection to {host}")
    return _original_connect(self, address)


def _guarded_create_connection(address: object, *args: object, **kwargs: object) -> socket.socket:
    host = address[0] if isinstance(address, tuple) and address else address
    if not _is_loopback(host):
        raise OSError(f"offline validation blocked non-loopback connection to {host}")
    return _original_create_connection(address, *args, **kwargs)


socket.socket.connect = _guarded_connect
socket.create_connection = _guarded_create_connection
