"""eqmq-viewer: a live web map of your bot's zone, as an MQ2-style plugin.

Draws the zone from the EverQuest client's own map files (<zone>.txt and the _1.._3 layer
files in the client's maps folder; never shipped with the SDK) and puts the bot, players,
NPCs, pets, EQEmu bots and corpses on top, updated live from the SDK's state.

    EQMQ_MAPS=C:/EQ/RoF2Client/maps  (folder with poknowledge.txt etc.)
    EQMQ_VIEWER_PORT=8765            (default)

    bot = await eqmq.connect(...)
    await bot.run([MapViewer(bot)])   # then open http://127.0.0.1:8765

Display only: the page cannot send commands. It listens on 127.0.0.1 only.
No dependencies beyond the standard library: plain HTTP plus Server-Sent Events.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from importlib import resources

from ..plugin import MQPlugin

log = logging.getLogger("eqmq.viewer")

UPDATE_INTERVAL = 0.5  # seconds between live updates sent to the page


def parse_map_file(path: str) -> dict:
    """Parse one EQ map file. Coordinates are kept in map space, which is (-x, -y) of game space."""
    lines, points = [], []
    with open(path, encoding="latin-1") as f:
        for row in f:
            kind, _, rest = row.strip().partition(" ")
            fields = [t.strip() for t in rest.split(",")]
            try:
                if kind == "L" and len(fields) >= 9:
                    x1, y1, z1, x2, y2, z2 = (float(v) for v in fields[:6])
                    r, g, b = (int(float(v)) for v in fields[6:9])
                    lines.append([round(x1, 1), round(y1, 1), round(z1, 1), round(x2, 1), round(y2, 1), round(z2, 1),
                                  f"#{r:02x}{g:02x}{b:02x}"])
                elif kind == "P" and len(fields) >= 8:
                    x, y, z = (float(v) for v in fields[:3])
                    r, g, b = (int(float(v)) for v in fields[3:6])
                    size = int(float(fields[6]))
                    label = ",".join(fields[7:]).replace("_", " ")
                    points.append([round(x, 1), round(y, 1), round(z, 1), f"#{r:02x}{g:02x}{b:02x}", size, label])
            except ValueError:
                continue  # skip malformed rows
    return {"lines": lines, "points": points}


class MapStore:
    """Finds and caches a zone's map layers."""

    LAYERS = ["", "_1", "_2", "_3"]

    def __init__(self, directory: str | None):
        self.directory = directory
        self.cache: dict[str, dict] = {}

    def get(self, short_name: str) -> dict:
        if short_name in self.cache:
            return self.cache[short_name]
        layers = []
        if self.directory and os.path.isdir(self.directory):
            for suffix in self.LAYERS:
                path = os.path.join(self.directory, f"{short_name}{suffix}.txt")
                if os.path.isfile(path):
                    layer = parse_map_file(path)
                    layer["name"] = "base" if not suffix else f"layer {suffix[1:]}"
                    layers.append(layer)
        result = {"zone": short_name, "layers": layers,
                  "error": None if layers else f"no map files for {short_name} in {self.directory or '(EQMQ_MAPS not set)'}"}
        self.cache[short_name] = result
        return result


class MapViewer(MQPlugin):
    def __init__(self, bot, host: str = "127.0.0.1", port: int | None = None, maps: str | None = None):
        super().__init__(bot)
        self.host = host
        self.port = port or int(os.environ.get("EQMQ_VIEWER_PORT", "8765"))
        self.maps = MapStore(maps or os.environ.get("EQMQ_MAPS"))
        self._server: asyncio.base_events.Server | None = None
        self._page = resources.files(__package__).joinpath("index.html").read_bytes()

    async def on_load(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        log.info("map viewer at http://%s:%d", self.host, self.port)
        print(f"eqmq-viewer: http://{self.host}:{self.port}", flush=True)

    async def on_clean(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    # ---- state for the page ----

    def snapshot(self) -> dict:
        bot = self.bot
        me, zone = bot.Me, bot.Zone
        if not me or not zone:
            return {"connected": False}
        return {
            "connected": bot.connected,
            "zone": zone.ShortName,
            "zone_name": zone.Name,
            "me": {"id": me.ID, "name": me.Name, "x": me.X, "y": me.Y, "z": me.Z, "heading": me.Heading,
                   "target": me.TargetID, "hp": me.PctHPs},
            "spawns": [
                {"id": s.ID, "n": s.Name, "t": s.Type, "l": s.Level, "x": round(s.X, 1), "y": round(s.Y, 1),
                 "z": round(s.Z, 1), "h": round(s.Heading), "hp": s.PctHPs, "ai": s.Headless}
                for s in bot.Spawns()
            ],
        }

    # ---- a deliberately tiny HTTP server ----

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await asyncio.wait_for(reader.readline(), 10)
            method, path, _ = request.decode("latin-1").split(" ", 2)
            while (await reader.readline()) not in (b"\r\n", b"\n", b""):
                pass  # headers are not needed
            path = path.split("?", 1)[0]

            if method != "GET":
                await self._send(writer, 405, "text/plain", b"GET only")
            elif path == "/":
                await self._send(writer, 200, "text/html; charset=utf-8", self._page)
            elif path == "/map":
                zone = self.bot.Zone
                body = json.dumps(self.maps.get(zone.ShortName) if zone else {"layers": [], "error": "not in a zone"})
                await self._send(writer, 200, "application/json", body.encode())
            elif path == "/events":
                await self._events(writer)
            else:
                await self._send(writer, 404, "text/plain", b"not found")
        except (ConnectionError, asyncio.TimeoutError, ValueError):
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def _send(self, writer, status: int, content_type: str, body: bytes) -> None:
        reason = {200: "OK", 404: "Not Found", 405: "Method Not Allowed"}.get(status, "")
        writer.write(f"HTTP/1.1 {status} {reason}\r\nContent-Type: {content_type}\r\nContent-Length: {len(body)}\r\n"
                     f"Cache-Control: no-store\r\nConnection: close\r\n\r\n".encode() + body)
        await writer.drain()

    async def _events(self, writer) -> None:
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-store\r\n"
                     b"Connection: keep-alive\r\n\r\n")
        while self.bot.connected:
            writer.write(f"data: {json.dumps(self.snapshot(), separators=(',', ':'))}\n\n".encode())
            await writer.drain()
            await asyncio.sleep(UPDATE_INTERVAL)
        writer.write(f"data: {json.dumps({'connected': False})}\n\n".encode())
        await writer.drain()
