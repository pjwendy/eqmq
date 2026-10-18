"""Walk a headless character to a spawn or a location and back, printing progress.

    python examples/walk.py --token hc_... --character Bifar --to "Mirao"
    python examples/walk.py --token hc_... --character Bifar --loc -125 -30
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import eqmq  # noqa: E402


async def progress(bot: eqmq.Bot) -> None:
    while bot.connected:
        print(f"  at {bot.Me.Loc}  heading {bot.Me.Heading:.0f}", flush=True)
        await asyncio.sleep(1)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9100)
    ap.add_argument("--token", required=True)
    ap.add_argument("--character", required=True)
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument("--to", help="walk to the nearest spawn matching this MQ2 search, e.g. 'npc Mirao'")
    target.add_argument("--loc", nargs=2, type=float, metavar=("Y", "X"), help="walk to /loc Y X")
    ap.add_argument("--stay", type=float, default=5, help="seconds to wait before walking back")
    args = ap.parse_args()

    bot = await eqmq.connect(args.host, args.port, args.token, args.character)
    home = (bot.Me.X, bot.Me.Y, bot.Me.Z)
    print(f"{bot.Me.Name} starts at {bot.Me.Loc}")

    if args.to:
        spawn = bot.Spawn(args.to)
        if not spawn:
            print(f"nothing matches '{args.to}'")
            await bot.close()
            return
        print(f"walking to {spawn.Name} at {spawn.Loc} ({spawn.Distance:.0f} away)")
        dest = (spawn.X, spawn.Y, spawn.Z)
    else:
        y, x = args.loc
        print(f"walking to {y}, {x}")
        dest = (x, y, None)

    ticker = asyncio.create_task(progress(bot))
    result = await bot.moveto(*dest, wait=True)
    print(f"{result.Status} at {result.Loc}")

    await asyncio.sleep(args.stay)
    print("walking back")
    result = await bot.moveto(*home, wait=True)
    print(f"{result.Status} at {result.Loc}")

    ticker.cancel()
    await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
