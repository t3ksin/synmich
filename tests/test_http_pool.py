"""Connection reuse, exclusive leases and streamed-download authentication."""

import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch

import pytest
import requests

from synmich.core.http_pool import SessionPool
from synmich.core.immich import ImmichClient
from synmich.core.synology import SynologyClient


@pytest.fixture
def http_server():
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self):
            super().setup()
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.server.connections.append(self.client_address)

        def do_GET(self):
            self.server.cookies.append(self.headers.get("Cookie"))
            body = b"\xff\xd8\xffimage" if self.path.startswith("/webapi") else b'{"id":"user"}'
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "image/jpeg" if self.path.startswith("/webapi") else "application/json",
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.connections = []
    server.cookies = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_immich_reuses_one_connection_for_multiple_api_calls(http_server):
    server, url = http_server
    client = ImmichClient(url, "key")
    try:
        for _ in range(8):
            assert client.me() == {"id": "user"}
        assert len(server.connections) == 1
        client.close()
        assert client.me() == {"id": "user"}
        assert len(server.connections) == 2
    finally:
        client.close()


def test_streamed_synology_download_reuses_connection_and_refreshes_cookies(http_server, tmp_path):
    server, url = http_server
    client = SynologyClient(url)
    client.sid = "sid"
    client.session = requests.Session()
    client.session.cookies.set("id", "old-cookie")
    try:
        for item_id in (1, 2):
            client.session.cookies.set("id", "old-cookie" if item_id == 1 else "renewed-cookie")
            path = client.download({"id": item_id, "filename": "photo.jpg"}, tmp_path)
            assert path.read_bytes() == b"\xff\xd8\xffimage"
        assert len(server.connections) == 1
        assert server.cookies == ["id=old-cookie", "id=renewed-cookie"]
    finally:
        client.close_downloads()
        client.session.close()


def test_concurrent_leases_never_share_a_session():
    pool = SessionPool()
    barrier = threading.Barrier(4)

    def worker(i):
        with pool.session() as session:
            session.cookies.set("worker", str(i))
            barrier.wait(timeout=3)
            assert session.cookies.get("worker") == str(i)
            return id(session)

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            identities = list(executor.map(worker, range(4)))
        assert len(set(identities)) == 4
    finally:
        pool.close()


def test_closing_pool_retires_active_leases_and_can_be_reused():
    with patch("synmich.core.http_pool.requests.Session", side_effect=[MagicMock(), MagicMock()]):
        pool = SessionPool()
        old = pool.acquire()
        pool.close()
        pool.release(old)
        old.close.assert_called_once()
        new = pool.acquire()
        assert new is not old
        pool.release(new)
        pool.close()
        new.close.assert_called_once()


def test_session_is_returned_after_exception():
    pool = SessionPool()
    try:
        with pytest.raises(RuntimeError):
            with pool.session() as session:
                raise RuntimeError("request failed")
        with pool.session() as next_session:
            assert next_session is session
    finally:
        pool.close()
