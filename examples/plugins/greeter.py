"""Reply to tells, at most once a minute per player. Adds /greet <name> and a Greeter TLO."""
import time

from eqmq import MQPlugin

COOLDOWN = 60


class Greeter(MQPlugin):
    async def on_load(self):
        self.last_reply: dict[str, float] = {}
        self.replies = 0
        self.bot.event("#1# tells you, '#2#'")(self.on_tell)
        self.bot.register_command("/greet", self.greet)
        self.bot.register_tlo("Greeter", lambda: {"Replies": self.replies, "Players": sorted(self.last_reply)})

    async def on_tell(self, who: str, text: str):
        now = time.monotonic()
        if now - self.last_reply.get(who, 0) < COOLDOWN:
            return
        self.last_reply[who] = now
        self.replies += 1
        await self.bot.tell(who, f"Hello {who}! I'm an AI-controlled character. You said: {text}")

    async def greet(self, rest: str):
        return await self.bot.say(f"Hail, {rest or 'everyone'}!")
