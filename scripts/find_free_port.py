"""Print the first free TCP port at or after the one requested.

start_app.bat uses this so a port that is already taken - another copy of the
dashboard, or anything else on 8501 - moves the app to the next free port
instead of failing the launch.

Usage:  python find_free_port.py [start] [how_many_to_try]
"""
from __future__ import annotations

import socket
import sys

DEFAULT_PORT = 8501
DEFAULT_SPAN = 25


CONNECT_TIMEOUT = 0.25


def _can_bind(family: int, host: str, port: int) -> bool:
    """Try a real bind, the way a server would.

    SO_REUSEADDR is deliberately not set: on Windows it allows binding a port
    that is already in use, which is the condition we are testing for.
    """
    try:
        sock = socket.socket(family, socket.SOCK_STREAM)
    except OSError:
        return True  # family unavailable, so it cannot be the blocker
    with sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _is_listening(port: int) -> bool:
    """True if something already answers on this port.

    Binding alone is not a reliable probe: Windows grants a second bind to
    [::], which is exactly where Streamlit listens, so a bind test reports a
    busy port as free. Connecting catches it.

    Only a completed connection counts as proof. A refusal means nothing is
    there, and a timeout is inconclusive rather than positive - with a local
    firewall in the way, connections to closed loopback ports time out instead
    of being refused, so treating a timeout as "busy" would reject every free
    port on such machines.
    """
    for family, host in ((socket.AF_INET, "127.0.0.1"),
                         (socket.AF_INET6, "::1")):
        if family == socket.AF_INET6 and not socket.has_ipv6:
            continue
        try:
            sock = socket.socket(family, socket.SOCK_STREAM)
        except OSError:
            continue
        with sock:
            sock.settimeout(CONNECT_TIMEOUT)
            try:
                sock.connect((host, port))
                return True
            except OSError:
                continue  # refused, timed out, or family unreachable
    return False


def is_free(port: int) -> bool:
    """True when no server holds the port and we can still bind it."""
    if _is_listening(port):
        return False
    return _can_bind(socket.AF_INET, "0.0.0.0", port)


def first_free(start: int, span: int) -> int | None:
    for port in range(start, start + span):
        if 0 < port <= 65535 and is_free(port):
            return port
    return None


def main(argv: list[str]) -> int:
    try:
        start = int(argv[1]) if len(argv) > 1 else DEFAULT_PORT
        span = int(argv[2]) if len(argv) > 2 else DEFAULT_SPAN
    except ValueError:
        start, span = DEFAULT_PORT, DEFAULT_SPAN

    port = first_free(start, span)
    if port is None:
        # Nothing free in the range: echo the request back and let Streamlit
        # report the real bind error.
        print(start)
        return 1
    print(port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
