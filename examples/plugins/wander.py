"""Idle around the spot the bot logged in at: every so often, walk to a random nearby point.

/wander on|off toggles it. A Soldier-style plugin: deterministic, no AI.
"""
import asyncio
import math
import random

from eqmq import CommandResult, MQPlugin

RADIUS = 40      # how far from camp to wander
PAUSE = (8, 20)  # seconds to idle between walks


class Wander(MQPlugin):
    async def on_load(self):
        me = self.bot.Me
        self.camp = (me.X, me.Y, me.Z)
        self.enabled = True
        self.walking = False
        self.next_walk = 0.0
        self.bot.on("move")(self.on_move)
        self.bot.register_command("/wander", self.toggle)

    async def on_frame(self):
        if not self.enabled or self.walking or self.bot.Me.Combat:
            return
        loop_time = asyncio.get_running_loop().time()
        if loop_time < self.next_walk:
            return
        angle = random.uniform(0, 2 * math.pi)
        dist = random.uniform(5, RADIUS)
        x, y, z = self.camp
        # set before sending: a MoveEvent (e.g. NO_PATH) can arrive before the CommandResult
        self.walking = True
        result = await self.bot.moveto(x + dist * math.cos(angle), y + dist * math.sin(angle), z)
        if not result:
            self.walking = False

    def on_move(self, result):
        self.walking = False
        loop_time = asyncio.get_running_loop().time()
        self.next_walk = loop_time + random.uniform(*PAUSE)

    async def toggle(self, rest: str):
        if rest.lower() not in ("on", "off"):
            return CommandResult(False, "usage: /wander on|off")
        self.enabled = rest.lower() == "on"
        if not self.enabled:
            await self.bot.stop()
        return CommandResult(True)

    async def on_clean(self):
        await self.bot.stop()
