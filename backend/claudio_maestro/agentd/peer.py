"""User id of the process on the other end of a Unix socket."""

import socket
import struct
import sys

# macOS: SOL_LOCAL and LOCAL_PEERCRED (sys/un.h); struct xucred starts with
# u_int cr_version, uid_t cr_uid.
_SOL_LOCAL = 0
_LOCAL_PEERCRED = 0x001


def peer_uid(sock: socket.socket) -> int | None:
    """uid of the peer, or None when the platform gives no way to know."""
    if sys.platform.startswith("linux"):
        raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _pid, uid, _gid = struct.unpack("3i", raw)
        return uid
    if sys.platform == "darwin":
        raw = sock.getsockopt(_SOL_LOCAL, _LOCAL_PEERCRED, 76)
        _version, uid = struct.unpack_from("Ii", raw)
        return uid
    return None
