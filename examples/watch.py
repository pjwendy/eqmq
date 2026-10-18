"""Log a headless character in and print what it sees, once a second.

    python examples/watch.py --token hc_... --character Bifar
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import eqmq  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9100)
    ap.add_argument("--token", required=True)
    ap.add_argument("--character", required=True)
    ap.add_argument("--seconds", type=float, default=30)
    args = ap.parse_args()

    try:
        bot = await eqmq.connect(args.host, args.port, args.token, args.character)
    except eqmq.Refused as e:
        print(f"refused: {e}")
        return

    me, zone = bot.Me, bot.Zone
    print(f"{me.Name} (level {me.Level}) in {zone.Name} [{zone.ShortName}] at {me.Loc}")
    print(f"  HP {me.CurrentHPs}/{me.MaxHPs} ({me.PctHPs}%)  mana {me.PctMana}%  end {me.PctEndurance}%")
    print(f"  {bot.SpawnCount()} spawns: {bot.SpawnCount('npc')} npc, {bot.SpawnCount('pc')} pc, "
          f"{bot.SpawnCount('pet')} pet, {bot.SpawnCount('corpse')} corpse")

    for _ in range(int(args.seconds)):
        if not bot.connected:
            print("disconnected")
            return
        me = bot.Me
        near = bot.Spawns("radius 60")[:3]
        nearby = ", ".join(f"{s.Name} ({s.Type} {s.Level}, {s.Distance:.0f})" for s in near) or "nobody"
        players = ", ".join(f"{s.Name}{' [AI]' if s.Headless else ''} @ {s.Loc}" for s in bot.Spawns("pc")) or "none"
        print(f"[{me.Loc}] HP {me.PctHPs}%  target {bot.Target.Name if bot.Target else '-'}  "
              f"nearby: {nearby}  |  players: {players}")
        await asyncio.sleep(1)

    await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
