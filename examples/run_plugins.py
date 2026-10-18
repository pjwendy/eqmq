"""Log a headless character in and run every plugin in a directory.

    python examples/run_plugins.py --token hc_... --character Bifar --plugins examples/plugins
"""
import argparse
import asyncio
import logging
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
    ap.add_argument("--plugins", default=os.path.join(os.path.dirname(__file__), "plugins"))
    ap.add_argument("--eqstr", default=None, help="path to your client's eqstr_us.txt")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    bot = await eqmq.connect(args.host, args.port, args.token, args.character, eqstr=args.eqstr)
    bot.on("line")(lambda line: print(f"  | {line}", flush=True))
    print(f"{bot.Me.Name} is in {bot.Zone.Name} at {bot.Me.Loc}; running plugins (Ctrl+C to stop)")
    try:
        await bot.run(args.plugins)
    finally:
        await bot.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
