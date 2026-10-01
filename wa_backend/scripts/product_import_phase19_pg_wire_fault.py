"""Test-only PostgreSQL wire faults; never fabricate a successful COMMIT.

The existing disposable P19 gate owns the upstream. Only plaintext loopback
traffic from its execution engine is routed here. No SQL/credentials are logged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import socket
import struct
import threading
import time

UPSTREAM_PORT = 55446
PROXY_PORT = 55447


def read_exact(connection: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        part = connection.recv(size - len(data))
        if not part:
            raise EOFError
        data.extend(part)
    return bytes(data)


def frame(connection: socket.socket) -> tuple[bytes, bytes, bytes]:
    header = read_exact(connection, 5)
    length = struct.unpack("!I", header[1:])[0]
    if not 4 <= length <= 2 * 1024 * 1024:
        raise RuntimeError("Unexpected bounded PG frame size.")
    payload = read_exact(connection, length - 4)
    return header[:1], payload, header + payload


@dataclass
class WireConnection:
    client: socket.socket
    server: socket.socket
    pid: int = 0
    staged: bool = False
    products: bool = False
    commit_fault: bool = False
    prepared: dict[bytes, str] = field(default_factory=dict)
    released: threading.Event = field(default_factory=threading.Event)

    def close(self) -> None:
        self.released.set()
        for connection in (self.client, self.server):
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()


class CommitFaultProxy:
    """Relay actual PG frames; drop exactly one selected connection/COMMIT ACK."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.mode: str | None = None
        self.observed: dict | None = None
        self.target: WireConnection | None = None
        self.connections: list[WireConnection] = []
        self.threads: list[threading.Thread] = []
        self.listener = socket.socket()
        # Do not reuse an occupied port or redirect to another database.
        self.listener.bind(("127.0.0.1", PROXY_PORT))
        self.listener.listen(8)
        self.listener.settimeout(.2)
        self.stopped = threading.Event()
        self.acceptor = threading.Thread(target=self._accept, daemon=True)
        self.acceptor.start()

    def arm(self, mode: str) -> None:
        if mode not in {"staging_abort", "staging_commit", "execution_commit"}:
            raise ValueError("Unknown bounded wire fault.")
        with self.lock:
            if self.mode is not None:
                raise RuntimeError("Previous fault was not consumed.")
            self.mode, self.observed, self.target = mode, None, None

    def claim(self, connection: WireConnection, *, commit: bool) -> None:
        with self.lock:
            mode = self.mode
            match = (mode == "staging_abort" and connection.staged and not commit) or (
                commit and (
                    (mode == "staging_commit" and connection.staged) or
                    (mode == "execution_commit" and connection.products)
                )
            )
            if not match:
                return
            self.mode = None
            self.target = connection
            if commit:
                connection.commit_fault = True
            else:
                self.observed = {"case": mode, "backend_pid": connection.pid,
                                 "server_commit_seen": False}

    def release(self) -> None:
        with self.lock:
            target = self.target
        if target is None:
            raise RuntimeError("No owned fault connection.")
        target.close()

    def wait_observed(self, seconds: float = 40) -> dict:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            with self.lock:
                if self.observed is not None:
                    return dict(self.observed)
            time.sleep(.05)
        raise RuntimeError("Expected real PostgreSQL wire boundary was not observed.")

    def _accept(self) -> None:
        while not self.stopped.is_set():
            try:
                client, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            upstream = socket.create_connection(("127.0.0.1", UPSTREAM_PORT), timeout=5)
            # Idle pooled connections must remain alive until the gate closes.
            upstream.settimeout(None)
            connection = WireConnection(client, upstream)
            self.connections.append(connection)
            for target in (self._frontend, self._backend):
                thread = threading.Thread(target=target, args=(connection,), daemon=True)
                self.threads.append(thread)
                thread.start()

    def _frontend(self, connection: WireConnection) -> None:
        try:
            length = read_exact(connection.client, 4)
            size = struct.unpack("!I", length)[0]
            if not 8 <= size <= 64 * 1024:
                raise RuntimeError("Invalid synthetic PG startup.")
            startup = read_exact(connection.client, size - 4)
            # SSL/GSS negotiation is deliberately unsupported, never downgraded.
            if struct.unpack("!I", startup[:4])[0] != 196608:
                raise RuntimeError("Proxy requires explicit plaintext isolated startup.")
            connection.server.sendall(length + startup)
            while True:
                kind, payload, raw = frame(connection.client)
                marker = None
                if kind in {b"P", b"Q"}:
                    name, sql = payload.split(b"\0", 1) if kind == b"P" else (b"", payload)
                    sql = sql.split(b"\0", 1)[0].upper()
                    if b"INSERT INTO PRODUCT_IMPORT_ROWS" in sql:
                        marker = "staged"
                    elif b"INSERT INTO PRODUCTS " in sql or b"INSERT INTO PRODUCTS(" in sql:
                        marker = "products"
                    elif sql.rstrip(b"; \r\n") == b"COMMIT":
                        marker = "commit"
                    if kind == b"P":
                        # SQLAlchemy/asyncpg may reuse the same prepared INSERT
                        # in a later transaction without sending its SQL again.
                        if marker:
                            connection.prepared[name] = marker
                        marker = None
                elif kind == b"B":
                    statement = payload.split(b"\0", 2)[1]
                    marker = connection.prepared.get(statement)
                elif kind == b"C" and payload[:1] == b"S":
                    connection.prepared.pop(payload[1:].rstrip(b"\0"), None)
                if marker == "staged":
                    connection.staged = True
                    self.claim(connection, commit=False)
                elif marker == "products":
                    connection.products = True
                elif marker == "commit":
                    self.claim(connection, commit=True)
                connection.server.sendall(raw)
        except (EOFError, OSError):
            pass
        finally:
            connection.close()

    def _backend(self, connection: WireConnection) -> None:
        try:
            while True:
                kind, payload, raw = frame(connection.server)
                if kind == b"K":
                    connection.pid = struct.unpack("!I", payload[:4])[0]
                if kind == b"C" and payload == b"COMMIT\0" and connection.commit_fault:
                    # Received from PostgreSQL AFTER its durable commit, BEFORE
                    # CommandComplete (and subsequent ReadyForQuery) reach asyncpg.
                    with self.lock:
                        self.observed = {
                            "case": "execution_commit" if connection.products else "staging_commit",
                            "backend_pid": connection.pid, "server_commit_seen": True,
                            "command_complete_forwarded": False,
                        }
                    # Parent reads durable state/locks while ACK is withheld.
                    # Fail closed if parent exits, with a bounded 12s hold.
                    connection.released.wait(12)
                    return
                connection.client.sendall(raw)
                if kind == b"Z" and payload == b"I":
                    connection.staged = connection.products = False
        except (EOFError, OSError):
            pass
        finally:
            connection.close()

    def close(self) -> None:
        self.stopped.set()
        self.listener.close()
        for connection in self.connections:
            connection.close()
        self.acceptor.join(timeout=2)
        for thread in self.threads:
            thread.join(timeout=1)
