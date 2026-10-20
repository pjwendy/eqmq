"""eqmq-viewer: a live web map of your bot's zone, as an MQ2-style plugin.

Draws the zone from the EverQuest client's own map files (<zone>.txt and the _1.._3 layer
files in the client's maps folder; never shipped with the SDK) and puts the bot, players,
NPCs, pets, EQEmu bots and corpses on top, updated live from the SDK's state.

    EQMQ_MAPS=C:/EQ/RoF2Client/maps  (folder with poknowledge.txt etc.)
    EQMQ_NAV=C:/server/maps/nav      (optional: the server's navmeshes, drawn by the Navmesh box)
    EQMQ_VIEWER_PORT=8765            (default)
    EQMQ_VIEWER_HOST=127.0.0.1       (default; another address, e.g. 0.0.0.0, to view it from elsewhere)

    bot = await eqmq.connect(...)
    await bot.run([MapViewer(bot)])   # then open http://127.0.0.1:8765

Display only: the page cannot send commands. It listens on 127.0.0.1 unless EQMQ_VIEWER_HOST says otherwise.
No dependencies beyond the standard library: plain HTTP plus Server-Sent Events.

Subclasses can add routes (override route()) and page controls (extra_controls: HTML for the
toolbar; extra_script: a <script> block, which gets an "eqmq-state" event on every update).
"""
from __future__ import annotations

import asyncio
import collections
import json
import logging
import os
import re
import time
from importlib import resources

from ..plugin import MQPlugin
from .navmesh import NavStore

log = logging.getLogger("eqmq.viewer")

UPDATE_INTERVAL = 0.5  # seconds between live updates sent to the page

CLASS_SHORT = {1: "WAR", 2: "CLR", 3: "PAL", 4: "RNG", 5: "SHD", 6: "DRU", 7: "MNK", 8: "BRD", 9: "ROG", 10: "SHM",
               11: "NEC", 12: "WIZ", 13: "MAG", 14: "ENC", 15: "BST", 16: "BER"}
NO_MANA = {1, 7, 9, 16}  # warriors, monks, rogues, berserkers

# game text worth a line in the page's log, and how to colour it
LOG_LINES = [
    (re.compile(r"welcome to level|you have gained a level", re.I), "level"),
    (re.compile(r"you have been slain|you died", re.I), "death"),
    (re.compile(r"you have slain|has been slain by", re.I), "kill"),
    (re.compile(r"you gain (party |group |raid )?experience|you have gained .* experience", re.I), "good"),
    (re.compile(r"you have looted|you receive \d+ ", re.I), "loot"),
    (re.compile(r"you have learned|you have scribed|have accepted", re.I), "good"),
]


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

    def zones(self) -> list[str]:
        """Short names of every zone with a map file, sorted."""
        if not self.directory or not os.path.isdir(self.directory):
            return []
        names = set()
        for filename in os.listdir(self.directory):
            stem, ext = os.path.splitext(filename)
            if ext.lower() != ".txt":
                continue
            if len(stem) > 2 and stem[-2] == "_" and stem[-1] in "123":
                stem = stem[:-2]
            names.add(stem.lower())
        return sorted(names)


class MapViewer(MQPlugin):
    extra_controls = ""  # HTML added to the toolbar
    extra_script = ""    # HTML (a <script> block) added at the end of the page

    def __init__(self, bot, host: str | None = None, port: int | None = None, maps: str | None = None,
                 nav: str | None = None):
        super().__init__(bot)
        self.host = host or os.environ.get("EQMQ_VIEWER_HOST", "127.0.0.1")
        self.port = port or int(os.environ.get("EQMQ_VIEWER_PORT", "8765"))
        self.maps = MapStore(maps or os.environ.get("EQMQ_MAPS"))
        self.nav = NavStore(nav or os.environ.get("EQMQ_NAV"))
        self._server: asyncio.base_events.Server | None = None
        page = resources.files(__package__).joinpath("index.html").read_text(encoding="utf-8")
        page = page.replace("<!--eqmq:controls-->", self.extra_controls).replace("<!--eqmq:script-->", self.extra_script)
        self._page = page.encode("utf-8")
        self._log: collections.deque = collections.deque(maxlen=500)
        self._log_id = 0

    def note(self, text: str, kind: str = "info") -> None:
        """Add a line to the page's log (kinds: info, plan, kill, loot, level, death, good)."""
        self._log_id += 1
        self._log.append({"id": self._log_id, "t": time.strftime("%H:%M"), "kind": kind, "text": str(text)[:300]})

    def _on_line(self, line: str) -> None:
        for pattern, kind in LOG_LINES:
            if pattern.search(line):
                self.note(line, kind)
                return

    async def on_load(self) -> None:
        self.bot.on("line")(self._on_line)
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        log.info("map viewer at http://%s:%d", self.host, self.port)
        print(f"eqmq-viewer: http://{self.host}:{self.port}", flush=True)

    async def on_clean(self) -> None:
        self.bot.off("line", self._on_line)
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    # ---- state for the page ----

    def snapshot(self) -> dict:
        bot = self.bot
        me, zone = bot.Me, bot.Zone
        if not me or not zone:
            return {"connected": False}
        group = []
        members = bot.Group.All if bot.Group else ()
        names = [m.Name for m in members] or [me.Name]
        spawns = {s.ID: s for s in bot.Spawns()}
        for name in names:
            m = next((g for g in members if g.Name == name), None)
            if name == me.Name:
                group.append({"name": me.Name, "cls": CLASS_SHORT.get(me.ClassID, "?"), "level": me.Level,
                              "hp": me.PctHPs, "mana": me.PctMana, "has_mana": me.MaxMana > 0,
                              "leader": bool(m and m.Leader) or not members, "here": True,
                              "exp": round(me.ExpPct, 1), "aa": round(me.AAExpPct, 1), "aa_points": me.AAPoints,
                              "aa_split": me.AASplit, "has_aa": me.Level >= 51 or me.AAPoints > 0 or me.AAExpPct > 0
                              or me.AASplit > 0})
                continue
            s = spawns.get(m.ID) if m and m.ID else None
            group.append({"name": name, "cls": CLASS_SHORT.get(s.ClassID, "?") if s else "?", "level": s.Level if s else 0,
                          "hp": s.PctHPs if s else 0, "mana": s.PctMana if s else 0,
                          "has_mana": bool(s and s.ClassID not in NO_MANA), "leader": bool(m and m.Leader),
                          "here": s is not None})
        return {
            "group": group,
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

    async def route(self, method: str, path: str, body: bytes) -> tuple[int, str, bytes] | None:
        """Answer a request with (status, content type, body), or None for 404. Override to add routes."""
        if method != "GET":
            return None
        if path == "/":
            return 200, "text/html; charset=utf-8", self._page
        if path == "/map":
            zone = self.bot.Zone
            data = self.maps.get(zone.ShortName) if zone else {"layers": [], "error": "not in a zone"}
            return 200, "application/json", json.dumps(data).encode()
        if path == "/navmesh":
            zone = self.bot.Zone
            data = self.nav.get(zone.ShortName) if zone else {"polys": [], "links": [], "error": "not in a zone"}
            return 200, "application/json", json.dumps(data, separators=(",", ":")).encode()
        return None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await asyncio.wait_for(reader.readline(), 10)
            method, path, _ = request.decode("latin-1").split(" ", 2)
            headers = {}
            while (line := await reader.readline()) not in (b"\r\n", b"\n", b""):
                name, _, value = line.decode("latin-1").partition(":")
                headers[name.strip().lower()] = value.strip()
            length = min(int(headers.get("content-length", "0") or 0), 65536)
            body = await asyncio.wait_for(reader.readexactly(length), 10) if length else b""
            path = path.split("?", 1)[0]

            if method == "GET" and path == "/events":
                await self._events(writer)
                return
            result = await self.route(method, path, body)
            if result is None:
                await self._send(writer, 404, "text/plain", b"not found")
            else:
                await self._send(writer, *result)
        except (ConnectionError, asyncio.TimeoutError, asyncio.IncompleteReadError, ValueError):
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def _send(self, writer, status: int, content_type: str, body: bytes) -> None:
        reason = {200: "OK", 400: "Bad Request", 404: "Not Found", 409: "Conflict"}.get(status, "")
        writer.write(f"HTTP/1.1 {status} {reason}\r\nContent-Type: {content_type}\r\nContent-Length: {len(body)}\r\n"
                     f"Cache-Control: no-store\r\nConnection: close\r\n\r\n".encode() + body)
        await writer.drain()

    async def _events(self, writer) -> None:
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-store\r\n"
                     b"Connection: keep-alive\r\n\r\n")
        sent = 0
        while self.bot.connected:
            state = self.snapshot()
            state["log"] = [e for e in self._log if e["id"] > sent]
            if state["log"]:
                sent = state["log"][-1]["id"]
            writer.write(f"data: {json.dumps(state, separators=(',', ':'))}\n\n".encode())
            await writer.drain()
            await asyncio.sleep(UPDATE_INTERVAL)
        writer.write(f"data: {json.dumps({'connected': False})}\n\n".encode())
        await writer.drain()
