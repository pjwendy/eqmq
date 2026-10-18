"""Spawn your EQEmu bots, group them, and fight the nearest easy mob together.

    python examples/bot_group.py --token hc_... --character Bifar --bots Brokkar Elowen Kazrin Tamsin

Create the bots once first, as any player would, e.g. /bot ^botcreate Brokkar 1 8 0
(name, class, race, gender). Needs Bots:Enabled and HeadlessClients:AllowBots, and a zone
that allows combat (the Plane of Knowledge doesn't).
"""
import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import eqmq  # noqa: E402


async def fight(bot: eqmq.Bot, mob: eqmq.Spawn, timeout: float = 90) -> bool:
    """Walk to the mob, target and face it, auto-attack, and send the bots in. True if it died."""
    await bot.moveto(mob.X, mob.Y, mob.Z, wait=True, timeout=40)
    await bot.target(mob)
    await asyncio.sleep(0.5)
    await bot.face(mob)
    await bot.attack(True)
    await bot.DoCommand("/bot ^attack spawned")
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            m = bot.Spawn(f"id {mob.ID}")
            if not m or m.Type == "Corpse" or m.PctHPs == 0:
                return True
            if m.Distance > 8:  # it moved: follow it
                await bot.moveto(m.X, m.Y, m.Z, wait=True, timeout=10)
            await bot.face(m)  # melee needs us facing it, as for a real player
            print(f"  {m.Name} {m.PctHPs}%  me {bot.Me.PctHPs}%  "
                  + ", ".join(f"{b.Name} {b.PctHPs}%" for b in bot.Bots()), flush=True)
            await asyncio.sleep(2)
        return False
    finally:
        await bot.attack(False)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9100)
    ap.add_argument("--token", required=True)
    ap.add_argument("--character", required=True)
    ap.add_argument("--bots", nargs="+", required=True, help="names of bots you've already created")
    ap.add_argument("--max-level", type=int, default=3, help="only fight NPCs up to this level")
    args = ap.parse_args()

    bot = await eqmq.connect(args.host, args.port, args.token, args.character)
    bot.on("line")(lambda line: print(f"  | {line}", flush=True))
    try:
        for name in args.bots:
            await bot.DoCommand(f"/bot ^botspawn {name}")
            await asyncio.sleep(1.5)
        await asyncio.sleep(2)
        for b in bot.Bots():
            if not (bot.Group and bot.Group.Member(b.Name)):
                await bot.invite(b)
                await asyncio.sleep(1)
        group = bot.Group
        print(f"group: {[m.Name for m in group.All] if group else 'none'}")

        mobs = [m for m in bot.Spawns(f"npc range 1 {args.max_level} radius 400")
                if m.OwnerID == 0 and "guard" not in m.Name.lower()]
        if not mobs:
            print("nothing easy to fight nearby")
            return
        mob = mobs[0]
        print(f"fighting {mob.Name} (level {mob.Level}), {mob.Distance:.0f} units away")
        print("killed it" if await fight(bot, mob) else "gave up")
    finally:
        await bot.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
