# Getting started with eqmq

This walks you from a server with nothing on it to a script that plays a character: logging in,
reading what it sees, walking, fighting, reacting to chat, commanding its bots, and running for days.
The [README](../README.md) is the tour of the API and [reference.md](reference.md) lists all of it.

- [1. A server that allows it](#1-a-server-that-allows-it)
- [2. Install eqmq](#2-install-eqmq)
- [3. Log in and look around](#3-log-in-and-look-around)
- [4. Do things](#4-do-things)
- [5. React: events](#5-react-events)
- [6. Bots](#6-bots)
- [7. Plugins and the live map](#7-plugins-and-the-live-map)
- [8. Running for days](#8-running-for-days)
- [9. When it goes wrong](#9-when-it-goes-wrong)

## 1. A server that allows it

eqmq drives **headless characters**, which only exist on a server running the headless module from
[pjwendy/Server](https://github.com/pjwendy/Server) (branch `headless`), with the module turned on by
its operator. It doesn't work against an ordinary EQEmu server, and it isn't meant to: running
scripted characters is the operator's decision.

If you run the server, its [quick start](https://github.com/pjwendy/Server/blob/headless/docs/headless.md#quick-start)
takes you through building it, turning on the listener and the rules, and issuing a token. If someone
else runs it, ask them for three things:

- the address and port of its headless listener (by default `127.0.0.1:9100`, on the server itself);
- a **token** for your account (`hc_` and 64 hex characters);
- a character on that account (or make one in the game).

## 2. Install eqmq

Python 3.10 or later; the only dependency is `protobuf`.

```sh
pip install git+https://github.com/pjwendy/eqmq
```

Or clone it and `pip install -e eqmq` to change it as you go.

## 3. Log in and look around

```python
import asyncio
import eqmq

async def main():
    bot = await eqmq.connect("127.0.0.1", 9100, token="hc_...", character="Bifar")
    me = bot.Me
    print(f"{me.Name}, level {me.Level}, {me.PctHPs}% HP, in {bot.Zone.Name} at {me.Loc}")

    for s in bot.Spawns("npc radius 150"):
        print(f"  {s.Name}, level {s.Level}, {s.Distance:.0f} away{', after us' if s.WillAggro else ''}")

    await bot.close()

asyncio.run(main())
```

`connect` returns once the character is in its zone and the first snapshot has arrived. From then on
eqmq keeps a mirror of the character's state, updated four times a second. `bot.Me`, `bot.Target`,
`bot.Spawn(...)`, `bot.Group`, `bot.Zone` and the rest read that mirror, so reading is free and
never waits on the network. Spawn searches use MacroQuest's syntax: `"npc radius 50 rat"`,
`"id 1234"`, `"pc guild"`.

`examples/watch.py` prints what a character sees, once a second.

## 4. Do things

Every action is an `async` method, and most also have a MacroQuest slash command:

```python
rat = bot.Spawn("npc radius 200 rat")
if rat:
    result = await bot.moveto(rat.X, rat.Y, rat.Z, wait=True, timeout=bot.walk_time(rat.Distance))
    print(result.Status)                 # ARRIVED, STUCK, NO_PATH, ...
    await bot.target(rat)
    await bot.face(rat)
    await bot.attack(True)

await bot.DoCommand("/cast 1")          # the spell in gem 1
await bot.DoCommand("/g Pulling!")      # group chat
await bot.DoCommand("/travelto qeynos2") # walk through the zone line to a neighbouring zone
```

A command's result says only that the server **accepted** it, as a player's keypress is accepted. What
happens next arrives as state and events: the spell lands (`bot.Target.Buffs`), the mob dies (an
event), the walk arrives (`MoveResult`). So a script waits on what it can see, not on the command:

```python
while bot.Target and bot.Target.PctHPs > 0:   # until the mob is dead
    await asyncio.sleep(0.25)
```

Walks follow the zone's navmesh at the character's run speed, open doors it has keys for, and keep
round mobs that would aggro it on long journeys. `examples/walk.py` walks to a spawn and back.

## 5. React: events

MacroQuest-style `#event` patterns match any line of game text; `#1#`, `#2#` capture words:

```python
@bot.event("#1# tells you, '#2#'")
async def tell(sender, text):
    await bot.tell(sender, "Hello! I'm a scripted character.")

@bot.event("You have been slain by #1#!")
async def died(killer):
    print("killed by", killer)
```

There are typed events too, for what isn't a line of text (a zone change, a death, a skill-up, a
loot window): `@bot.on("death")`, `@bot.on("zone")` and the others are in [reference.md](reference.md#results-and-events).

## 6. Bots

A headless character can own EQEmu bots, as any player can (if the server allows bots). Bot commands
go through `/bot` and are said as `^command`:

```python
await bot.DoCommand("/bot ^botcreate Brokkar 1 8 0")   # once: a warrior bot
await bot.spawn_bots(["Brokkar"])                       # ^botspawn, and invite it to follow
await bot.DoCommand("/bot ^attack spawned")             # the bots attack your target
```

`bot.Group` then shows them, `bot.Bots` lists the spawned ones (as spawns), and `bot.BotGear` every bot
the character owns with what each one wears and its buffs. The fork adds bot commands of its own: `^pack` (a bot carries things for you),
`^bank`, `^feign` and `^corpsedrag`; see the server's [Bots](https://github.com/pjwendy/Server/blob/headless/docs/headless.md#bots).
`examples/bot_group.py` spawns the bots, groups them and fights the nearest easy mob together.

## 7. Plugins and the live map

A plugin is a subclass of `eqmq.MQPlugin` with hooks (`on_load`, `on_frame` every frame, `on_clean`),
and slash commands and TLOs of its own (`bot.register_command`, `bot.register_tlo`). Plugins load from
a folder, so behaviours can be written once and mixed:

```sh
python examples/run_plugins.py --token hc_... --character Bifar --plugins examples/plugins
```

`examples/plugins/` has a greeter, a wanderer and the map viewer. `eqmq.viewer.MapViewer` serves a live
map of the character's zone in the browser: the zone from the client's map files, every spawn
coloured by con, the group, the enemies on the group, the route a walk is taking, and the game text.
Its state is also served as server-sent events at `/events`, for anything else that wants to draw it.
The README's [Plugins](../README.md#plugins) and [map viewer](../README.md#the-map-viewer) sections
have the details.

## 8. Running for days

- **Restarting your program doesn't lose the character.** If it goes away without `close()` (a crash,
  a restart, a deploy), the server holds the character, its bots and its fights frozen for the
  server's `HoldSeconds` (5 minutes by default). Connect again and you take it back where it was:
  `bot.resumed` is `True`. `bot.close()` logs it out for good; `bot.close(hold=True)` leaves it held,
  as a crash would.
- **Zoning keeps the session.** The connection stays open across a zone change; you get a
  `ZoneChange` and a new snapshot.
- **Mind the rate limit.** The server allows `CommandRateLimit` commands a second per character (20 by
  default) and refuses the rest. Poll state, not the server.
- **Death is a game state, not an error.** The character respawns at its bind; its corpse waits.
  A rez is accepted from its own bots, its group, a guildmate's bot (when the corpse is by it) and a GM.

## 9. When it goes wrong

| Symptom | Likely cause |
|---|---|
| `connect` raises with a `Refused` reason | The server's [troubleshooting table](https://github.com/pjwendy/Server/blob/headless/docs/headless.md#troubleshooting) says what each reason means: the module is off, the token is wrong, a limit is reached, the zone is blocked. |
| Connection refused outright | The listener isn't on, or you have the wrong address or port. |
| A walk ends `NO_PATH` or `STUCK` | The zone's navmesh has a gap there. `MoveResult.Nav` notes say where (`no_mesh_here`, `not_connected`, `locked` door...). |
| A command returns `ok=False` | Its `error` says why: out of range, no line of sight, not enough mana, the rate limit. |
| Nothing happens after `ok=True` | The server accepted it but the game said no: watch the events (`You cannot see your target.`). |
