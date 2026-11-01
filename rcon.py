"""Small Source RCON client shared by the panel and background updater."""

from __future__ import annotations

from dataclasses import dataclass
import socket
import struct
import time

AUTH_PACKET_TYPE = 3
AUTH_RESPONSE_TYPE = 2
COMMAND_PACKET_TYPE = 2
AUTH_REQUEST_ID = 1
COMMAND_REQUEST_ID = 2
PALWORLD_RESPONSE_ID = 0
MAX_PACKET_SIZE = 4 * 1024 * 1024


class RconConnectionClosed(RuntimeError):
    """Raised when the server closes a completed RCON response."""


class RconDeadlineExceeded(RuntimeError):
    """Raised when a response body cannot be read before the shared deadline.

    Kept distinct from socket.timeout on purpose: the read loop treats a socket
    timeout as "response finished, go idle", and a stalled transfer is not that.
    """


@dataclass(frozen=True)
class RconResult:
    """The result of a single Source RCON command."""

    success: bool
    acknowledged: bool
    response: str = ""
    message: str = ""


def execute_rcon_command(
    host: str,
    port: int,
    password: str,
    command: str,
    timeout: float = 10,
    allow_no_response: bool = False,
) -> RconResult:
    """Run a Source RCON command and collect its response until it becomes idle.

    Palworld does not acknowledge an empty completion sentinel and can respond
    with packet ID 0 rather than echoing the command request ID. A shared
    deadline and short idle grace preserve compatible multi-packet responses.
    """
    if not password:
        return RconResult(False, False, message="RCON_PASSWORD is not configured")

    deadline = time.monotonic() + timeout

    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            def set_remaining_timeout() -> None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("response timed out")
                sock.settimeout(remaining)

            def recv_exact(length: int) -> bytes:
                data = bytearray()
                while len(data) < length:
                    # Recompute the budget for every chunk. Setting the socket
                    # timeout once let a server that dribbles one byte just
                    # under the timeout keep the connection alive indefinitely,
                    # so `timeout` bounded each recv() instead of the command.
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RconDeadlineExceeded("response timed out")
                    sock.settimeout(remaining)
                    try:
                        chunk = sock.recv(length - len(data))
                    except socket.timeout as exc:
                        # Nothing at all yet means the server simply went idle --
                        # keep the historical "no acknowledgement" handling.
                        # Half a packet is a stalled transfer, and saying "the
                        # command was not acknowledged" would hide that.
                        if not data:
                            raise
                        raise RconDeadlineExceeded("response timed out") from exc
                    if not chunk:
                        raise RconConnectionClosed("connection closed while reading response")
                    data.extend(chunk)
                return bytes(data)

            def send_packet(packet_id: int, packet_type: int, body_text: str) -> None:
                body = body_text.encode("utf-8") + b"\x00\x00"
                payload = struct.pack("<ii", packet_id, packet_type) + body
                sock.sendall(struct.pack("<i", len(payload)) + payload)

            def recv_packet() -> tuple[int, int, str]:
                size = struct.unpack("<i", recv_exact(4))[0]
                if size < 10 or size > MAX_PACKET_SIZE:
                    raise RuntimeError("invalid response packet size")
                data = recv_exact(size)
                if data[-2:] != b"\x00\x00":
                    raise RuntimeError("invalid response packet terminator")
                packet_id, packet_type = struct.unpack("<ii", data[:8])
                return packet_id, packet_type, data[8:-2].decode("utf-8", errors="replace")

            send_packet(AUTH_REQUEST_ID, AUTH_PACKET_TYPE, password)
            packet_id, packet_type, _ = recv_packet()
            if packet_id == -1:
                return RconResult(False, False, message="Auth failed")
            if packet_id != AUTH_REQUEST_ID or packet_type != AUTH_RESPONSE_TYPE:
                raise RuntimeError("unexpected authentication response")

            send_packet(COMMAND_REQUEST_ID, COMMAND_PACKET_TYPE, command)

            responses: list[str] = []
            acknowledged = False
            first_response = True
            while True:
                try:
                    if first_response:
                        set_remaining_timeout()
                    else:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        sock.settimeout(min(1.5, remaining))
                    packet_id, _, body = recv_packet()
                except socket.timeout:
                    break
                except RconConnectionClosed:
                    if acknowledged:
                        break
                    raise

                if packet_id not in {COMMAND_REQUEST_ID, PALWORLD_RESPONSE_ID}:
                    raise RuntimeError("unexpected command response packet")
                acknowledged = True
                if body.strip():
                    responses.append(body.strip())
                first_response = False

            if not acknowledged:
                if allow_no_response:
                    return RconResult(
                        True,
                        False,
                        message="Command sent; this Palworld command did not return an RCON response",
                    )
                return RconResult(False, False, message="The server did not acknowledge the command")
            if responses:
                return RconResult(True, True, response="\n".join(responses))
            return RconResult(True, True, message="Command acknowledged; the server returned no text")
    except Exception as exc:
        return RconResult(False, False, message=str(exc))


def rcon_command(host: str, port: int, password: str, command: str, timeout: float = 10) -> str:
    """Run a command and retain the legacy string return contract."""
    result = execute_rcon_command(host, port, password, command, timeout)
    if result.success:
        return result.response
    return f"[RCON Error] {result.message}"
