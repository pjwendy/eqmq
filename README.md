# eqmq

A Python SDK for EQEmu **headless characters**: characters that live inside the server with no game
client, driven by your program. It speaks the server's headless protocol and gives it
MacroQuest's vocabulary, so `bot.Me.PctHPs`, `bot.Spawn("npc radius 50")`, `/target`, `#event` and
plugins all work the way MQ2 users expect. No MacroQuest code is used: only the names.

eqmq only works on servers that run the headless module **and whose operator has turned it on and
given you a token**. Setting up the server is covered in the fork's
[`docs/headless.md`](https://github.com/pjwendy/eqemu-headless/blob/headless/docs/headless.md).

- [Install](#install)
- [Quick start](#quick-start)
- [What you can read](#what-you-can-read)
- [What you can do](#what-you-can-do)
- [Slash commands](#slash-commands)
- [Events](#events)
- [Plugins](#plugins)
- [The map viewer](#the-map-viewer)
- [Things to know](#things-to-know)
- [Examples](#examples)

## Install

Python 3.10 or later. The only dependency is `protobuf`.

```
pip install -e path/to/eqmq
```

## Quick start

```python
import asyncio
import eqmq

async def main():
    bot = await eqmq.connect("127.0.0.1", 9100, token="hc_...", character="Bifar")
    me = bot.Me
    print(f"{me.Name}, level {me.Level}, {me.PctHPs}% HP, in {bot.Zone.Name} at {me.Loc}")

    for s in bot.Spawns("npc radius 100"):
        print(f"  {s.Name} (level {s.Level}) {s.Distance:.0f} away")

    await bot.close()

asyncio.run(main())
```

`connect` returns once the character is in its zone and the first snapshot has arrived. If your
program went away without closing the session (a crash or a restart), the server held the character
frozen, with its bots and its fights, and `connect` takes that session back: `bot.resumed` is `True`
and everything is as it was when you left. `bot.close()` ends the session for good (the character
logs out); `bot.close(hold=True)` leaves it held, as a crash would. From then
on the SDK keeps a mirror of the character's state, updated four times a second. Everything you
read is a frozen snapshot of that mirror, so reading is free and never waits on the network.

## What you can read

The TLOs are properties of the `Bot`. Each one returns a fresh, read-only object.

| TLO | | MQ2 |
|---|---|---|
| `bot.Me` | You: `Name`, `Level`, `ClassID`, `RaceID`, `Gender` (0 male, 1 female, 2 neutral), `CurrentHPs`/`MaxHPs`/`PctHPs`, mana and endurance the same way, `X`/`Y`/`Z`/`Heading`/`Loc`, `TargetID`, `Sitting`/`Standing`, `Combat` (auto-attack), `Casting`/`CastingID`, `Gems` and `Gem(n or name)`, `Buffs` and `Buff(name)`, coin (`Platinum`... and `Money` in copper), `Weight`/`Capacity`/`Encumbered`, `Haters`/`Engaged`, `ExpPct`, `AAExpPct`, `AAPoints`, `AASplit`, `RunSpeed`, `Air`/`MaxAir` (seconds of breath under water), `GameHour`, `Disciplines` | `${Me}` |
| `bot.Target` | Your target, as a `Spawn` (or `None`) | `${Target}` |
| `bot.Spawn(search)`, `bot.Spawns(search)`, `bot.SpawnCount(search)`, `bot.NearestSpawn(n, search)` | Spawns in the zone matching an MQ2-style search | `${Spawn[]}`, `${SpawnCount[]}`, `${NearestSpawn[]}` |
| `bot.Group` | `All` (members, you first: each a `GroupMember` with `Name`, `ID`, `Leader`, `Bot` and `Buffs`, what is on it), `Members`, `Leader`, `Member(n or name)` | `${Group}` |
| `bot.Me.Resists`, `BotGear.Resists`, `BotGear.Buffs` | Each bot's buffs (with their slots, seen in a raid too), and resists now, yours and each bot's (`Magic`, `Cold`, `Fire`, `Poison`, `Disease`: base, gear, buffs and AAs) | `${Me.svMagic}` |
| `bot.Raid` | The raid you are in, or None: `All` (each a `RaidMember` with `Name`, `ID`, `Group` 0-11 or `RAID_GROUPLESS`, `GroupLeader`, `RaidLeader`, `Bot`, `Class`, `Level`), `Members`, `Leader`, `Member(name)`, `Group(n)`, `Groups`, `Ungrouped` | `${Raid}` |
| `bot.Zone` | `ShortName`, `Name`, `ID`, `Exits` (one per neighbouring zone, with where its zone line is) and `Exit(short_name)` | `${Zone}` |
| `bot.Inventory()`, `bot.Bank()`, `bot.FindItem(name)`, `bot.FindItemCount(name)` | Items, with their slots and stats; an item with sockets has `AugSockets` (the type of each of the six) and `Augs` (the item id in each, 0 empty), an augment `AugType` (the socket types it fits, a bitmask), `AugRestrict` and `AugDistiller` | `${FindItem[]}` |
| `bot.Book()`, `bot.BookSpell(name)` | The spell book | `${Me.Book[]}` |
| `bot.Bots()`, `bot.BotGear()` | Your EQEmu bots in the zone, and what each one wears | (EQEmu only) |
| `bot.Haters()` | NPCs with you on their hate list, nearest first | |

A `Spawn` has `ID`, `Name`, `Type` (`PC`, `NPC`, `Pet`, `Bot`, `Corpse`), `Level`, `ClassID`,
`RaceID`, `X`/`Y`/`Z`/`Heading`/`Loc`, `PctHPs`, `PctMana`, `TargetID` (for a mob in a fight, who it's
hitting), `OwnerID` (pets), `Headless` (another headless character), `Gender` (0 male, 1 female, 2 neutral), `Primary` and `Secondary` (the item
materials held in the hands, to draw a model with), `CastingID` (the spell it is casting, 0 if none: `Casting`), `Status` (bits: 1 mezzed, 2 rooted,
4 stunned, 8 feared or fleeing, 16 charmed: `Mezzed`, `Rooted`, `Stunned`, `Feared`, `Charmed`), `Distance` (from you) and, for an NPC, `AggroRange` (the radius it notices you in, 0 if it never aggros), `Buffs` (an NPC that is fighting, or has you on its hate list: the spells on it), `AssistRange` (the radius in which it calls others) and `Aggro` (bits: 1 hostile on sight, 2 may aggro, 4 aggros even a character it cons grey to), by the server's own aggro rules: `KOS`, `MayAggro`, `AggrosGrey` and `WillAggro(my_level, invisible)` read them.

**Spawn searches** use a subset of MQ2's syntax: `pc`, `npc`, `pet`, `bot`, `corpse`, `headless`,
`id <n>`, `radius <n>`, `zradius <n>`, `range <min> <max>` (levels), and any other words match the
name, ignoring case. For example `bot.Spawn("npc radius 60 gnoll")` or `bot.Spawns("corpse radius 30")`.

## What you can do

Actions are coroutines. Most return a `CommandResult`, which is truthy if the server accepted the
command (its `error` says why not). Acceptance isn't the outcome: whether the spell landed or the
mob died shows up in state and events, as it would on a player's screen.

| | |
|---|---|
| `target(spawn or id)`, `face(spawn)`, `attack(on=True)` | Target, face, auto-attack. |
| `say(text)`, `tell(to, text)`, `group(text)`, `chat(channel, text)` | Talk. `say("#...")` is a GM command (if your account may), `say("^...")` an EQEmu bot command. |
| `sit()`, `stand()` | |
| `moveto(x, y, z, wait=False)` | Walk along the server's navmesh at your run speed. With `wait=True` you get a `MoveResult` when the walk ends: `ARRIVED`, `STOPPED`, `STUCK`, `NO_PATH`, `ZONE_LINE`, `LOCKED` (a door you have no key for) or `REFUSED`. |
| `route_length(x, y, z)` | How far that walk would be, without walking (`None`: no way there). |
| `route_path(x, y, z)` | The points of that walk in order (at most about 120), without walking; `None` if there's no way there. |
| `zone_plan(short_name)` | The walk `zone_to` would take to the zone line, without walking: its length and how much of it is a swim. |
| `surface()` | Under water: swim straight up for air (`Me.Air` says how long you have). |
| `stop()` | Stop walking. `moveto` stands a sitting character up first, and waits for the stand-up, so the walk isn't refused. |
| `zone_to(short_name)` | Walk to the zone line for a neighbouring zone and through it. Returns a `ZoneChange` once you're there. |
| `gm_zone(short_name)` | `#zone` there (needs GM status). |
| `cast(spell, target, wait=False)`, `stopcast()`, `memorize(gem, spell)`, `scribe(scroll)` | Spells, by gem number or name. |
| `consider(spawn)` | A `Consider`: `Color` (`green`, `lightblue`, `blue`, `white`, `yellow`, `red`, `grey`) and `Faction` (`ally` ... `scowls`). |
| `loot(corpse)` | Loot a corpse. A `LootResult`: the `Items` taken, and coin. |
| `open_merchant(npc)`, `buy(npc, slot, qty)`, `sell(npc, item, qty)`, `close_merchant(npc)` | Shopping. `open_merchant` returns the merchant's list. |
| `send_parcel(npc, item, to, note)`, `retrieve_parcel(npc, parcel)` | Parcels, at an open parcel merchant: `open_merchant` returns `ParcelMerchant` and the `Parcels` waiting for you (`Parcel`: `Name`, `Quantity`, `From`, `Note`). Not attuned items, nor no-drop ones unless the server lets no-drop be traded (`World:FVNoDropFlag`); one parcel every 30 seconds. |
| `move_item(from_slot, to_slot)` | Move items between inventory, bags, worn slots and the bank. |
| `click_object(object_id)`, `combine(container_slot)`, `close_object()` | Tradeskills. `click_object` opens a world container (an oven, forge, loom, brew barrel, kiln...) by its id in the zone's object table, within reach; fill it with `move_item(slot, WORLD_SLOT + n)`; `combine()` (default `WORLD_CONTAINER`) is the Combine button, or pass an inventory bag's slot for a portable container. The product and any skill-up come as items and text. Products land on the cursor (one already there queues the next behind it: empty it between combines). |
| `click_door(door_id)` | Click a door by its id, as the client does (stand within reach first): a teleporter or a Plane of Knowledge book takes you where it goes (`ZoneChange`). |
| `drag_corpse(corpse)`, `drop_corpse(corpse)` | `/corpse drag` and `/corpse drop`: a corpse of yours, or one you are consented to, follows you. |
| `augment(item_slot, socket, action=0, distiller_slot=-1)` | The client's augment window: the augment on the cursor (`move_item` to the cursor first) into a socket (0-5) of a worn or carried item (action 0); safely out with its distiller (1, the augment comes to the cursor), swapped (2) or destroyed (3). The server checks the socket's type against the augment's `AugType` and the worn slots, and says why it won't in chat | the augment window |
| `aa_exp(percent)`, `buy_aa(rank_id)` | AA: the share of experience going to AA (the client's slider; 0 off), and one rank of an ability bought with a point (`rank_id` is the `aa_ranks.id` of the next rank; the server checks the level, the price and the prerequisites and says why when it won't). AA experience only starts at level 51. |
| `destroy(item)` | Destroy an item, as the client's Destroy button. |
| `pack_give(bot, item)`, `pack_list(bot)`, `pack_take(bot, slot)` | A bot's pack (`^pack`): what it carries in its general slots and bags, as `PackItem`s; put an item in, take one back to your cursor. |
| `ability(name)` | A combat ability: kick, bash, backstab, taunt, frenzy, the monk strikes; sneak, hide, feign death (`ABILITIES`). |
| `discipline(spell_id)` | A discipline you know (`Me.Disciplines`). |
| `pet(command)`, `Pet()` | Command your pet (`"attack"`, `"back off"`, `"follow"`, `"taunt on"`, ... `PET_COMMANDS`); your pet. |
| `use_item(item)` | Right-click an item: a click effect, a potion, a tome. |
| `invite(who)`, `disband()` | Groups. |
| `buff_remove(who, slot)` | Click a beneficial buff off yourself (`None`) or one of your bots, by its slot (`Buff.Slot`; `Me.Buffs` and `BotGear.Buffs` carry slots), as the buff window does. |
| `raid_invite(who)`, `raid_remove(who)`, `raid_move(who, group)` | Raids, as the raid window: invite a player who is ungrouped or leads a group (the whole group comes in) or a bot of yours, making a raid if you have none; take a member out (None: leave); move a member to raid group 0-11 (None: no group). A headless character accepts a guildmate's or a GM's raid invite by itself and leaves anyone else's unanswered. |
| `spawn_bots(names)`, `give_to_bot(name, item, slot)` | Spawn and group your EQEmu bots; hand one an item. |
| `wait_zoned(timeout)` | Wait for the next zone change (after dying, or a teleport). |
| `walk_time(distance)` | A sensible timeout for walking that far at your current run speed. |

## Slash commands

`bot.DoCommand(line)` runs an MQ2/EQ-style command:

`/say` (`/s`), `/g` (`/gsay`), `/gu` (`/guildsay`), `/rsay`, `/ooc`, `/shout`, `/auction` (`/auc`),
`/tell` (`/t`, `/msg`), `/target` (`id <n>`, a name, a search, or `clear`), `/attack on|off`, `/sit`,
`/stand`, `/moveto loc <y> <x> [z]`, `/moveto id <n>` or `/moveto off`, `/face`, `/invite`, `/disband`, `/cast <gem|name>`, `/stopcast`, `/memspell <gem> <name>`,
`/consider` (`/con`), `/loot`, `/doability <name>`, `/disc <spell id>`, `/pet <command>`, `/zoneto <zone>` (`/travelto`), and `/bot ^...` for EQEmu bot
commands. Plugins can add their own (see below).

## Events

Typed events, with `@bot.on(kind)`:

| Kind | You get |
|---|---|
| `chat` | A `Chat`: `Channel` (`SAY`, `TELL`, `GROUP`, ...), `From`, `To`, `Text`, `Line` |
| `message` | A `Message`: a game message (`Line`, as the client prints it) |
| `line` | Every line of chat and game text, as a string |
| `move` | A `MoveResult`, whenever a walk ends |
| `zone` | A `ZoneChange` |
| `death` | A `Death` (yours): `Killer` |
| `skill` | A `SkillUp` |

And MQ2's `#event` patterns, matched against every line: `#*#` matches anything, `#1#` to `#9#`
capture.

```python
@bot.on("chat")
async def heard(chat):
    print(chat.Line)

@bot.event("#1# tells you, '#2#'")
async def tell(sender, text):
    await bot.tell(sender, f"You said: {text}")

@bot.event("You have been slain by #1#!")
async def slain(killer):
    print("killed by", killer)
```

Game messages the server sends as string ids are rendered from your client's `eqstr_us.txt`. Point
eqmq at it with `EQMQ_EQSTR` or `connect(..., eqstr=path)`. The file belongs to the client and isn't
shipped.

## Plugins

A plugin subclasses `MQPlugin`. It has `on_load` (once), `on_frame` (every 100 ms by default) and
`on_clean` (once, at the end). It can add slash commands and TLOs:

```python
from eqmq import MQPlugin

class Greeter(MQPlugin):
    async def on_load(self):
        self.count = 0
        self.bot.event("#1# tells you, '#2#'")(self.on_tell)
        self.bot.register_command("/greet", self.greet)
        self.bot.register_tlo("Greeter", lambda: {"Replies": self.count})

    async def on_tell(self, who, text):
        self.count += 1
        await self.bot.tell(who, f"Hello {who}!")

    async def greet(self, rest):
        return await self.bot.say(f"Hail, {rest or 'everyone'}!")

await bot.run([Greeter(bot)])          # or bot.run("path/to/plugins") to load every plugin there
```

Plugins run in your process, so they're a convention for organising code, not a sandbox. They only
ever see protocol state, never raw packets.

## The map viewer

`eqmq.viewer.MapViewer` is a plugin that serves a live map of the character's zone in the browser:

- The zone, drawn from the client's own map files, with its layers and labels.
- Every spawn, as a shape by type (circles for NPCs and pets, squares for players and bots, crosses
  for corpses) and coloured by how NPCs con to you.
- You, your target and your group, with HP, mana and experience.
- A log of the game text worth seeing (chat, experience, kills, loot, trades, deaths in the group).
- Optionally, the server's navmesh: the walkable area, with islands a character can't walk to in
  their own colours.
- An **Enemies** panel (and, in the guild's 3D player, an Enemies window): everything that has the group on its hate list or is hitting one of us, as the client's
  extended target window shows it: level, health, what is on it (mezzed, rooted, stunned, feared or fleeing, charmed, casting) and who it is after. They are ringed in red on the map.
- Point at anything for its name and **level** (a spawn: its type, health and place; a camp: its mobs, levels, spawns and respawn, and who holds it).
- On the guild's maps, a **Camps** layer: the zone's named hunting areas as circles (the camp soldier's pull radius), gold for this character's camp,
  blue for another leader's, grey for a free one, each with its name and the leaders camped there; and a **Trail** layer, where this character has
  been in the last half hour, coloured by what it was doing.
- The route a walk is taking, drawn as a line to where the character is going, and its model, race and gender, buffs and experience.
- Its state as server-sent events at `/events` (any origin may read it), which is what the guild's live 3D view draws from; `?v=log` opens the
  log and chat tab.

```python
from eqmq.viewer import MapViewer
await bot.run([MapViewer(bot)])        # then open http://127.0.0.1:8765
```

| Setting | |
|---|---|
| `EQMQ_MAPS` | Your client's `maps` folder (`<zone>.txt` and `_1` to `_3` layers). Never shipped. |
| `EQMQ_NAV` | The server's `maps/nav` folder, for the navmesh layer (optional). |
| `EQMQ_VIEWER_PORT` | Default 8765. |
| `EQMQ_VIEWER_HOST` | Default 127.0.0.1. |

The page only displays. It can't send the character commands.

## Things to know

- **Coordinates.** Everything takes and returns the game's `x, y, z`, but EverQuest's `/loc` prints
  `y, x, z`. `Loc` properties print in `/loc` order, so they match what players see.
- **Run speed.** `Me.RunSpeed` is how fast a walk goes now, in units per second: buffs, snares,
  horses and GM speed included, 0 while rooted. Use `walk_time(distance)` for walk timeouts rather
  than a fixed number.
- **Rate limit.** The server accepts `HeadlessClients:CommandRateLimit` commands a second (20 by
  default). A refused command says so in its `error`.
- **Combat text.** A client prints its own damage lines from the combat packets; a headless character gets the same wording as `message`/`line`
  events for what you, your group, your bots and your pets do and take: `X hits Y for N points of damage.` (with the verb for the kind of hit:
  slashes, crushes, pierces, bashes, kicks) and `X tries to hit Y, but misses!`. Spell damage arrives as the server's own messages.
- **Bots.** Your EQEmu bots stand still to cast and don't cast while moving, say `Pulling X.` and `Incoming X!` when one pulls and the mob has
  come for the group, and `^feign` lies a bot down feigning (a monk, necromancer or shadowknight). A bot of those classes that is losing a fight
  feigns by itself, and a pet near death is called off.
- **Ending a session** logs the character out at once (saved, no linkdead). `bot.close()` does it;
  so does your program exiting.
- **The server decides.** eqmq never bypasses a rule. A command is the packet a client would send,
  so casting while moving, attacking out of range or buying without money fail as they would for a
  player.

## Examples

In `examples/`:

| | |
|---|---|
| `watch.py` | Log in and print what the character sees, once a second. |
| `walk.py` | Walk to a spawn or a location and back. |
| `bot_group.py` | Spawn your EQEmu bots, group them, and fight the nearest easy mob together. |
| `run_plugins.py` | Run every plugin in a folder, e.g. `examples/plugins` (a tell greeter, a wanderer, the map viewer). |

```
python examples/watch.py --token hc_... --character Bifar
python examples/run_plugins.py --token hc_... --character Bifar --plugins examples/plugins
```

eqmq is released under the GPL, version 3 or later, like EQEmu.
