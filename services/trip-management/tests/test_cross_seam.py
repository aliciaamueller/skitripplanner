"""Integration test across the seam: cancelling calls Room Allocation over HTTP.

Room Allocation is replaced by a stub: a real HTTP server, started in this
test, that records the requests it gets. So the real request leaves
Trip Management over the network (urllib, ROOMS_URL, the timeout) without
needing the other service and its database running.
"""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import app as trip_app
import trip_management


class StubRoomAllocation(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        StubRoomAllocation.received.append(("POST", self.path))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "released"}')

    def log_message(self, *args):
        pass


@pytest.fixture
def rooms_stub(monkeypatch):
    """Run the stub on a free port and point ROOMS_URL at it."""
    StubRoomAllocation.received = []
    server = HTTPServer(("127.0.0.1", 0), StubRoomAllocation)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(trip_app, "ROOMS_URL", f"http://127.0.0.1:{server.server_port}")
    # The real listener, which conftest removes for the other tests.
    trip_management.on_registration_cancelled(trip_app.release_room)
    yield server
    server.shutdown()
    server.server_close()


def _confirmed_student(client):
    trip_id = client.post("/trips", json={
        "name": "Alps", "destination": "Tignes",
        "start_date": "2027-01-15", "end_date": "2027-01-20", "capacity": 5,
    }).get_json()["id"]
    registration_id = client.post(f"/trips/{trip_id}/registrations", json={
        "name": "Ana", "email": "ana@example.com",
    }).get_json()["id"]
    client.post(f"/registrations/{registration_id}/payment")
    return registration_id


def test_cancelling_tells_room_allocation_to_free_the_bed(rooms_stub):
    client = trip_app.app.test_client()
    registration_id = _confirmed_student(client)

    response = client.post(f"/registrations/{registration_id}/cancel")

    assert response.status_code == 200
    assert StubRoomAllocation.received == [
        ("POST", f"/registrations/{registration_id}/release"),
    ]


def test_cancel_is_rolled_back_when_room_allocation_is_down(rooms_stub):
    client = trip_app.app.test_client()
    registration_id = _confirmed_student(client)
    rooms_stub.shutdown()
    rooms_stub.server_close()

    response = client.post(f"/registrations/{registration_id}/cancel")

    assert response.status_code == 400
    assert "Room Allocation is unavailable" in response.get_json()["error"]
    status = client.get(f"/registrations/{registration_id}").get_json()["status"]
    assert status == "confirmed"
