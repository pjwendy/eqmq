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
# live streams (the map and the 3D view's /events) run in the runner, beside the leaders' own play: one snapshot per leader per tick, shared by
# everyone watching it, and only so many watchers (the operator, 9 Nov, before sharing the public pages: viewers mustn't slow the guild)
MAX_STREAMS = 6        # watchers of one leader at once
MAX_STREAMS_ALL = 24   # watchers of all the leaders on this runner at once
_streams_all = 0

CLASS_SHORT = {1: "WAR", 2: "CLR", 3: "PAL", 4: "RNG", 5: "SHD", 6: "DRU", 7: "MNK", 8: "BRD", 9: "ROG", 10: "SHM",
               11: "NEC", 12: "WIZ", 13: "MAG", 14: "ENC", 15: "BST", 16: "BER"}
NO_MANA = {1, 7, 9, 16}  # warriors, monks, rogues, berserkers

# game text worth a line in the page's log, and how to colour it (chat has its own handler)
LOG_LINES = [
    (re.compile(r"welcome to level|you have gained a level", re.I), "level"),
    (re.compile(r"you have been slain|you died", re.I), "death"),
    (re.compile(r"you have slain|has been slain by", re.I), "kill"),
    (re.compile(r"you gain (party |group |raid )?experience|you have gained .* experience", re.I), "good"),
    (re.compile(r"you have looted|you receive \d+ ", re.I), "loot"),
    (re.compile(r"\btrad(e|ing)\b|gives you|you give|has offered you", re.I), "trade"),
    (re.compile(r"you have learned|you have scribed|have accepted", re.I), "good"),
]
SLAIN = re.compile(r"^(.+?) (?:has been slain by|died)", re.I)


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
        self._chat_id = 0
        self._chatlog: collections.deque = collections.deque(maxlen=1500)  # the chat window: every line of game text, with its colour
        self._chat_line = ""
        # fn() -> {"rows": [[label, text], ...]} or None: what the shown character is doing and why,
        # in its own panel (an AI layer sets it; the SDK has no plans of its own)
        self.plan = None

    def note(self, text: str, kind: str = "info") -> None:
        """Add a line to the page's log (kinds: info, decision, zone, chat, trade, kill, loot, level, death, good)."""
        self._log_id += 1
        self._log.append({"id": self._log_id, "t": time.strftime("%H:%M"), "kind": kind, "text": str(text)[:300]})

    CHANNEL_TYPES = {"SAY": 256, "TELL": 257, "GROUP": 258, "GUILD": 259, "OOC": 260, "AUCTION": 261, "SHOUT": 262, "RAID": 258}

    def _chat_add(self, kind: int, line: str) -> None:
        """A line for the page's chat window (kind: the server's message type, which says its colour: events.Message.Type)."""
        self._chat_id += 1
        self._chatlog.append({"id": self._chat_id, "t": time.strftime("%H:%M:%S"), "k": int(kind), "x": str(line)[:400]})

    def _on_message(self, msg) -> None:
        if msg.Line:
            self._chat_add(msg.Type, msg.Line)

    def _on_skill(self, up) -> None:
        self._chat_add(270, up.Line)

    def _on_chat(self, chat) -> None:
        self._chat_line = chat.Line  # the "line" handler gets it next: don't log it twice
        self.note(chat.Line, "chat")
        self._chat_add(self.CHANNEL_TYPES.get(str(chat.Channel).upper(), 273), chat.Line)

    def _on_zone(self, change) -> None:
        """Zone lines, ports, gates, deaths and #zone all come through here."""
        if change.Status == "LEAVING":
            if time.monotonic() - getattr(self, "_zoning_since", -1e9) < 30 and getattr(self, "_zoning_to", None) == change.Zone:
                return  # the server says it twice (the zone change request, then its answer)
            self._zoning_since, self._zoning_to = time.monotonic(), change.Zone
            self.note(f"zoning to {change.Zone or 'another zone'}...", "zone")
        elif change.Status == "ARRIVED":
            took = time.monotonic() - getattr(self, "_zoning_since", time.monotonic())
            self._zoning_to = None
            zone = self.bot.Zone
            self.note(f"arrived in {zone.Name if zone else change.Zone} ({took:.0f}s)", "zone")
        elif change.Status == "REFUSED":
            self.note(f"couldn't zone to {change.Zone}: {change.Detail or 'refused'}", "zone")

    def _on_line(self, line: str) -> None:
        if line == self._chat_line:
            self._chat_line = ""
            return
        m = SLAIN.match(line)
        if m and self.bot.Group and any(g.Name.lower() == m.group(1).lower() for g in self.bot.Group.All):
            self.note(line, "death")  # one of the group died
            return
        for pattern, kind in LOG_LINES:
            if pattern.search(line):
                self.note(line, kind)
                return

    async def on_load(self) -> None:
        self.bot.on("chat")(self._on_chat)
        self.bot.on("message")(self._on_message)
        self.bot.on("skill")(self._on_skill)
        self.bot.on("line")(self._on_line)
        self.bot.on("zone")(self._on_zone)
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        log.info("map viewer at http://%s:%d", self.host, self.port)
        print(f"eqmq-viewer: http://{self.host}:{self.port}", flush=True)

    async def on_clean(self) -> None:
        self.bot.off("chat", self._on_chat)
        self.bot.off("message", self._on_message)
        self.bot.off("skill", self._on_skill)
        self.bot.off("line", self._on_line)
        self.bot.off("zone", self._on_zone)
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    # ---- state for the page ----

    icon_lookup = None   # set by a host that has the spell data: ids -> {spell id: icon number}
    _icons: dict = {}
    ICONS_DIR = os.environ.get("SPELL_ICONS_DIR") or os.path.join(os.path.expanduser("~"), "eq-assets", "spellicons")

    def _buff_rows(self, buffs) -> list:
        """[name, ticks, spell id, icon] for each buff; the icon is its picture's number on the client's sheets (-1 when unknown)."""
        rows = [(b.Name, b.Ticks, b.ID) for b in buffs][:40]
        need = [r[2] for r in rows if r[2] not in self._icons]
        if need and self.icon_lookup:
            try:
                got = self.icon_lookup(need)
            except Exception:
                got = {}
            for i in need:
                self._icons[i] = got.get(i, -1)
        return [[n, t, i, self._icons.get(i, -1)] for n, t, i in rows]

    def snapshot(self) -> dict:
        bot = self.bot
        me, zone = bot.Me, bot.Zone
        if not me or not zone:
            # (logged out, or logging in: the connection is up but the character's own state has not arrived)
            return {"connected": False, "phase": "in" if bot.connected else "out"}
        group = []
        members = bot.Group.All if bot.Group else ()
        names = [m.Name for m in members] or [me.Name]
        spawns = {s.ID: s for s in bot.Spawns()}
        for name in names:
            m = next((g for g in members if g.Name == name), None)
            if name == me.Name:
                group.append({"id": me.ID, "name": me.Name, "cls": CLASS_SHORT.get(me.ClassID, "?"), "cid": me.ClassID, "level": me.Level,
                              "hp": me.PctHPs, "mana": me.PctMana, "has_mana": me.MaxMana > 0,
                              "leader": bool(m and m.Leader) or not members, "here": True,
                              "exp": round(me.ExpPct, 1), "aa": round(me.AAExpPct, 1), "aa_points": me.AAPoints,
                              "aa_split": me.AASplit, "has_aa": me.Level >= 51 or me.AAPoints > 0 or me.AAExpPct > 0
                              or me.AASplit > 0, "buffs": self._buff_rows(me.Buffs)})
                continue
            s = spawns.get(m.ID) if m and m.ID else None
            group.append({"id": s.ID if s else 0, "name": name, "cls": CLASS_SHORT.get(s.ClassID, "?") if s else "?", "cid": s.ClassID if s else 0, "level": s.Level if s else 0,
                          "hp": s.PctHPs if s else 0, "mana": s.PctMana if s else 0,
                          "has_mana": bool(s and s.ClassID not in NO_MANA), "leader": bool(m and m.Leader),
                          "here": s is not None, "buffs": self._buff_rows(m.Buffs if m else ())})
        plan = None
        if self.plan:
            try:
                plan = self.plan()
            except Exception:
                log.debug("plan failed", exc_info=True)
        return {
            "phase": "out" if not bot.connected else "zoning" if getattr(self, "_zoning_to", None) else "world",  # (the 3D view's screens: logged out, zoning, in the world)
            "zoning_to": getattr(self, "_zoning_to", None) or "",
            "group": group,
            "plan": plan,
            "connected": bot.connected,
            "zone": zone.ShortName,
            "zone_name": zone.Name,
            "me": {"id": me.ID, "name": me.Name, "level": me.Level, "x": me.X, "y": me.Y, "z": me.Z, "heading": me.Heading,
                   "target": me.TargetID, "hp": me.PctHPs, "cast": me.CastingID, "atk": int(bool(me.Combat)), "hour": me.GameHour, "race": me.RaceID, "sex": me.Gender,
                   "mana": me.PctMana, "exp": round(me.ExpPct, 1), "aa": round(me.AAExpPct, 1), "aap": me.AAPoints, "cid": me.ClassID, "buffs": self._buff_rows(me.Buffs),
                   "haters": [h if isinstance(h, int) else h.ID for h in me.Haters][:40]},
            "spawns": [
                {"id": s.ID, "n": s.Name, "t": s.Type, "l": s.Level, "x": round(s.X, 1), "y": round(s.Y, 1),
                 "z": round(s.Z, 1), "h": round(s.Heading), "hp": s.PctHPs, "ai": s.Headless, "r": s.RaceID, "g": s.Gender, "m": s.PctMana, "tg": s.TargetID, "w1": s.Primary, "w2": s.Secondary,
                 "ar": s.AggroRange, "as": s.AssistRange, "ag": s.Aggro, "st": s.Status, "cs": s.CastingID, "bf": [[b.ID, b.Ticks] for b in s.Buffs] if s.Buffs else 0}
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
        if m := re.match(r"^/spellicon/(\d+)\.png$", path):  # (the client's pictures, cut out by tools/spell_icons.py)
            try:
                with open(os.path.join(self.ICONS_DIR, m.group(1) + ".png"), "rb") as fh:
                    return 200, "image/png", fh.read()
            except OSError:
                return None
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
                await self._events(writer, headers)
                return
            if method == "GET" and path == "/watchers":
                # who is watching live now (the dashboard's Visitors page asks over the internal network; the public proxy refuses this path)
                ws = list(getattr(self, "_watchers", {}).values())
                await self._send(writer, 200, "application/json", json.dumps({"leader": self.bot.Me.Name if self.bot.Me else "",
                                                                               "watchers": ws}).encode())
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

    def _shared_snapshot(self) -> dict:
        """The snapshot for this tick, made once and shared by every watcher (each adds only its own new log and chat lines)."""
        now = time.monotonic()
        cached = getattr(self, "_snap", None)
        if cached is None or now - cached[0] >= UPDATE_INTERVAL * 0.8:
            cached = (now, self.snapshot())
            self._snap = cached
        return cached[1]

    async def _events(self, writer, headers: dict | None = None) -> None:
        global _streams_all
        mine = getattr(self, "_streams", 0)
        if mine >= MAX_STREAMS or _streams_all >= MAX_STREAMS_ALL:
            body = b"Too many people are watching live right now: try again in a while."
            writer.write(b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: text/plain\r\nRetry-After: 60\r\nAccess-Control-Allow-Origin: *\r\n"
                         + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
            await writer.drain()
            return
        self._streams = mine + 1
        _streams_all += 1
        h = headers or {}
        peer = writer.get_extra_info("peername")
        who = {"ip": (h.get("x-forwarded-for", "").split(",")[0].strip() or (peer[0] if peer else "")),
               "agent": h.get("user-agent", "")[:200], "since": round(time.time())}
        if not hasattr(self, "_watchers"):
            self._watchers = {}
        self._watchers[id(writer)] = who
        try:
            await self._stream(writer)
        finally:
            self._watchers.pop(id(writer), None)
            self._streams = max(0, getattr(self, "_streams", 1) - 1)
            _streams_all = max(0, _streams_all - 1)

    async def _stream(self, writer) -> None:
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-store\r\n"
                     b"Access-Control-Allow-Origin: *\r\n"  # (another page on this machine, the 3D view, reads the stream)
                     b"Connection: keep-alive\r\n\r\n")
        sent = sent_chat = 0
        while True:  # (it goes on while the character is logged out and in again: the 3D view says so, and the stream ends only when the page does: a write fails)
            state = dict(self._shared_snapshot())  # (a shallow copy: the shared one isn't changed)
            state["log"] = [e for e in self._log if e["id"] > sent]
            if state["log"]:
                sent = state["log"][-1]["id"]
            state["chat"] = [e for e in self._chatlog if e["id"] > sent_chat]
            if state["chat"]:
                sent_chat = state["chat"][-1]["id"]
            writer.write(f"data: {json.dumps(state, separators=(',', ':'))}\n\n".encode())
            await writer.drain()
            await asyncio.sleep(UPDATE_INTERVAL)
        writer.write(f"data: {json.dumps({'connected': False})}\n\n".encode())
        await writer.drain()
