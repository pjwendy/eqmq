# eqmq reference

Generated from the code by `tools/gen_reference.py`; don't edit by hand. The README is the tour; this is the list. Names follow MacroQuest where MacroQuest has one (`Me.PctHPs`, `Spawn.Distance`), and the server's protocol is in [headless-protocol.md](https://github.com/pjwendy/Server/blob/headless/docs/headless-protocol.md).

- The session: [connect](#connect), [Bot](#bot), [CommandResult](#commandresult), [Refused](#refused), [MQPlugin](#mqplugin), [load_plugins](#load_plugins)
- Top-level objects (TLOs): [Me](#me), [Spawn](#spawn), [Group](#group), [GroupMember](#groupmember), [Raid](#raid), [RaidMember](#raidmember), [Zone](#zone), [ZoneExit](#zoneexit)
- What you carry and cast: [Item](#item), [Buff](#buff), [Gem](#gem), [BookSpell](#bookspell), [Resists](#resists), [BotGear](#botgear), [PackItem](#packitem)
- Results and events: [MoveResult](#moveresult), [NavNote](#navnote), [LootResult](#lootresult), [Merchant](#merchant), [Parcel](#parcel), [Consider](#consider), [Death](#death), [SkillUp](#skillup), [ZoneChange](#zonechange), [Chat](#chat), [Message](#message)
- [Slash commands](#slash-commands)
- [Constants](#constants)

## The session

### connect

`async connect(host: str, port: int, token: str, character: str, eqstr: str | None = None, timeout: float = 60) -> Bot`

Log a headless character in and return it once its first snapshot has arrived.

eqstr: path to your client's eqstr_us.txt, to render messages sent as string ids
(or set EQMQ_EQSTR).

### Bot

| Property | |
|---|---|
| `Group` | Your group, or None when not grouped. |
| `Me` |  |
| `Raid` | The raid you are in (everyone in it, you too), or None when not in one. |
| `Target` |  |
| `Zone` |  |
| `connected` |  |

| Method | |
|---|---|
| `Bank() -> list[Item]` | What's in your bank (slots 2000-2023 and the bags in them). |
| `Book() -> list[BookSpell]` | Your spellbook, lowest level first. |
| `BookSpell(name: str) -> BookSpell \| None` |  |
| `BotGear() -> list[BotGear]` | Your spawned EQEmu bots and what each one wears. |
| `Bots() -> list[Spawn]` | Your spawned EQEmu bots in this zone, nearest first. |
| `async DoCommand(line: str) -> CommandResult` | Run an MQ2/EQ-style slash command, e.g. "/target id 123" or "/tell Eboola hi". |
| `FindItem(name: str) -> Item \| None` | The first carried item whose name contains `name`, as ${FindItem[...]}. |
| `FindItemCount(name: str) -> int` |  |
| `Haters() -> list[Spawn]` | NPCs that have you on their hate list, nearest first. |
| `Inventory() -> list[Item]` | Everything you carry: worn, general slots, bags and cursor (not the bank). |
| `NearestSpawn(n: int, search: str = ) -> Spawn \| None` | The n-th nearest match (1-based), as ${NearestSpawn[n,...]}. |
| `Pet() -> Spawn \| None` | Your pet, if you have one here. |
| `Spawn(search: str = ) -> Spawn \| None` | The nearest spawn matching the search, as ${Spawn[...]}. |
| `SpawnCount(search: str = ) -> int` |  |
| `Spawns(search: str = ) -> list[Spawn]` | All spawns matching an MQ2 search string, nearest first. |
| `TLO(name: str) -> Any` |  |
| `async aa_exp(percent: int) -> CommandResult` | The share of experience going to AA, as the client's AA window slider (0 off, 100: no more levels; Me.AASplit says what it is). |
| `async ability(which: str \| int) -> CommandResult` | Use a combat ability as the client's ability buttons do, by name or EQ skill number: kick, bash (slam), backstab, taunt, frenzy, intimidation and the monk strikes act on your target; throwing and archery are the range button (what's in the range slot, at your target); sneak, hide and feign death on you. The server checks the skill and its reuse timer (it says "Ability recovery time not yet met." if you're early). As /doability. |
| `async attack(on: bool = True) -> CommandResult` |  |
| `async augment(item_slot: int, socket: int, action: int = 0, distiller_slot: int = -1) -> CommandResult` | The client's augment window. The augment to put in is on the cursor already (move_item to slot 33). item_slot is the item to be augmented, worn or carried (a bank slot isn't allowed); socket 0-5. action: 0 insert the cursor's augment, 1 remove the augment in the socket whole (it comes to the cursor; Item.AugDistiller says which distiller must be in distiller_slot, 0: none needed), 2 swap (insert the cursor's, the old one comes to the cursor; the distiller as for remove), 3 destroy the augment in the socket. The server checks the socket's type against the augment's AugType and the worn slots, and says why it won't in chat (recent_messages); the item's new Augs arrive in the next inventory. |
| `async bank_coin(copper: int, to_bank: bool = True) -> CommandResult` | Coin between what you carry and your bank, beside a banker, as the bank window does: this much in copper's worth (platinum first, then gold, silver and copper; a withdrawal rounds up in a bigger coin when the smaller don't make it up). Me.BankMoney is what's in the bank. |
| `async bank_list(bot_name: str, timeout: float = 4) -> tuple[list[PackItem], int]` | What one of your bots keeps in its bank (^bank: 24 slots and the bags in them; [PackItem], slots 2000 and up), and how many more things it has room for. Anywhere. |
| `async bank_put(bot_name: str, pack_slot: int, timeout: float = 4) -> CommandResult` | One of your bots banks what's in one of its pack slots (PackItem.Slot from pack_list): into its bank, onto a stack of the same, a bag into a free slot, anything else into a bag with room. A bag must be empty. Only with a banker near the bot. |
| `async bank_take(bot_name: str, bank_slot: int, timeout: float = 4) -> CommandResult` | One of your bots takes what's in one of its bank slots (from bank_list) back into its pack (then pack_take gives it to you). Only with a banker near the bot. |
| `async buff_remove(who: "Spawn \| int \| None", slot: int) -> CommandResult` | Click a beneficial buff off yourself (None) or one of your bots, by its slot (Buff.Slot), as the buff window does. |
| `async buy(npc: Spawn \| int, merchant_slot: int, quantity: int = 1) -> CommandResult` | Buy from an open merchant (its Item.Slot). The server checks coin, lore and room. |
| `async buy_aa(rank_id: int) -> CommandResult` | Spend AA points on one rank of an alternate advancement ability, as the client's AA window does (rank_id is aa_ranks.id, the next rank of the ability; the server checks the level, the price and the prerequisites and says why when it won't). |
| `async cast(spell: int \| str, target: Spawn \| int \| None = None, wait: bool = False, timeout: float = 30) -> CommandResult` | Cast the spell in a gem: a gem number (1-based) or a memorised spell's name, as /cast. |
| `async chat(channel: int, text: str, to: str = ) -> CommandResult` |  |
| `async click_door(door_id: int, timeout: float = 30.0) -> ZoneChange` | Click a door in this zone by its door id (0-255), as the client does: stand within its reach first. A door with a destination (a teleporter, a Plane of Knowledge book) zones you where it goes: returns once you're there (ARRIVED), or why not (REFUSED: the server's reason; TIMEOUT: clicked, but nothing took you anywhere: too far, or a door that only opens). |
| `async click_object(object_id: int) -> CommandResult` | Open a world container (a forge, oven, kiln, brew barrel, loom...) by its id in the zone's object table, as a click on it does: stand beside it first (the server checks). Put what you combine into its slots (WORLD_SLOT + 0...: move_item), then combine(); close_object() when done. |
| `async close(hold: bool = False) -> None` | End the session: the character logs out. A program that goes away without closing (it crashed, or it's restarting) leaves its characters held by the server, frozen with their fights, for its next connect to take back (bot.resumed); hold=True closes the same way on purpose. |
| `async close_merchant(npc: Spawn \| int) -> CommandResult` |  |
| `async close_object() -> CommandResult` | Close the world container opened (anything left in it comes back to the inventory). |
| `async combine(container_slot: int = 1000) -> CommandResult` | The Combine button: make what the recipe says from what's in a container (WORLD_CONTAINER: the world object opened with click_object; or an inventory bag's slot, for a portable one). The server rolls the skill: the product, or the loss of some components, land in the inventory and the messages in chat (recent_messages). |
| `async command(cmd: pb.Command) -> CommandResult` | Send a raw Command and wait for the server's CommandResult. |
| `async consider(spawn: Spawn \| int \| None = None, timeout: float = 5) -> Consider \| None` | /consider a spawn (default: your target). None if no answer came. |
| `async destroy(item: Item \| int) -> CommandResult` | Destroy an item (all of a stack), as the client's Destroy button: pick it up (whatever was on the cursor goes where it was) and destroy what's on the cursor. |
| `async disband() -> CommandResult` | As /disband: removes your target from the group if you lead it, else leaves. |
| `async discipline(spell_id: int) -> CommandResult` | Use a discipline you know (Me.Disciplines), as the combat abilities window: on your target, or yourself. The server applies its reuse timer. |
| `async drag_corpse(corpse: Spawn \| int) -> CommandResult` | /corpse drag: a corpse (yours, or one you're consented to) follows you as you move, within the server's drag distance (Character:DragCorpseDistance). |
| `async drop_corpse(corpse: Spawn \| int \| None = None) -> CommandResult` | /corpse drop: stop dragging a corpse (None: every corpse you drag). |
| `event(pattern: str) -> Callable` | MQ2 #event: @bot.event("#1# tells you, '#2#'") is called with the captures. |
| `async face(spawn: Spawn \| int \| None = None) -> CommandResult` | Turn to face a spawn (None: your target), as /face. Melee needs you facing your target. |
| `free_book_slot() -> int \| None` |  |
| `async give(npc: Spawn \| int, item: Item \| int, quantity: int = 0, more: list[tuple[Item \| int, int]] \| None = None) -> CommandResult` | Hand an item from your inventory (all of a stack by default) to an NPC beside you, as the trade window does: its script takes it (a quest's hand-in). Not while it's fighting. A player of your guild that is a headless session in the same zone works too (the server plays both sides of the trade window; a no-drop item is refused). more: further (item or slot, quantity) in the same trade, up to seven (a hand-in of several: the script looks at the whole trade). |
| `async give_to_bot(bot_name: str, item: Item \| int, slot: int \| None = None, timeout: float = 5) -> CommandResult` | Hand an item from your inventory to one of your bots (^inventorygive), optionally into a worn slot. Whatever it wore there comes back to your cursor. Not while engaged. |
| `async gm_zone(short_name: str, timeout: float = 90) -> ZoneChange` | Zone with the GM command #zone (needs GM status) and wait until in the new zone. |
| `async group(text: str) -> CommandResult` |  |
| `async heal_hold(seconds: float) -> CommandResult` | No heal on yourself from bots for `seconds` (at most 600; 0 lifts it): a raid puller on a hate list before the main tank has its mob, since a heal on someone hated puts the healer on every hate list that has them. Bots skip you as a heal target, and their group heals while you're in reach. |
| `async invite(who: Spawn \| str \| None = None) -> CommandResult` | Invite a player or one of your bots to your group (None: your target), as /invite. |
| `async loot(corpse: Spawn \| int, timeout: float = 10, peek: bool = False, only: list[str] \| None = None) -> LootResult` | Loot everything from a corpse (walk within ~10 units first). peek: take nothing, only see what's on it (Left; the coin is taken, as opening it does). only: take just these items (a name each), the rest left on it (a raid's drops shared out). The server refuses every item while something is on the cursor (empty it first). |
| `async memorize(gem: int, spell: int \| str \| None, wait: bool = True, timeout: float = 15) -> CommandResult` | Memorise a spell from your book into gem (1-based); None forgets it. As /memspell. |
| `async move_item(from_slot: int, to_slot: int, quantity: int = 0) -> CommandResult` | Move an item, swapping with whatever is there: equip it, or put a bag in a general slot. |
| `async moveto(x: float, y: float, z: float \| None = None, wait: bool = False, timeout: float = 300, avoid: bool = False) -> CommandResult \| MoveResult` | Walk to a point (in-game x, y, z; /loc prints y first) along the navmesh at run speed. |
| `off(kind: str, fn: Callable) -> None` | Unregister a handler added with on(). |
| `on(kind: str) -> Callable` | Register a handler: "chat" gets a Chat, "message" a Message, "line" every line, "move" a MoveResult, "zone" a ZoneChange, "death" a Death (yours), "skill" a SkillUp (also a line, as the client prints it). |
| `async open_merchant(npc: Spawn \| int, timeout: float = 5) -> Merchant \| None` | Open a merchant's window (stand within ~20 units, as the client must). None if it didn't open. |
| `async pack_give(bot_name: str, item: Item \| int, timeout: float = 4) -> CommandResult` | Put an item from your inventory into one of your bots' packs (^pack: its general slots and the bags in them, carried, not worn): onto a stack of the same, a bag into a free slot, anything else into a bag with room. A bag must be empty. Not while engaged or trading. |
| `async pack_list(bot_name: str, timeout: float = 4) -> tuple[list[PackItem], int]` | What one of your bots carries in its pack ([PackItem], best read once per town trip), and how many more things it has room for. |
| `async pack_take(bot_name: str, slot: int, timeout: float = 4) -> CommandResult` | Take back what's in a pack slot (PackItem.Slot) of one of your bots: it comes to your cursor (put it away with move_item). A bag only when it's empty; not a lore item you already have. |
| `async pet(command: str \| int) -> CommandResult` | Command your pet, as /pet: "attack" (your target), "back off", "follow", "guard", "taunt on", "hold", "sit", ... (PET_COMMANDS), or EQEmu's pet command number. |
| `async raid_invite(who: Spawn \| str \| None = None) -> CommandResult` | Invite into your raid (making one with you and your group if you have none), as the raid window's invite: a player who is ungrouped or leads a group (the group comes too), or a bot of yours (ungrouped or leading a bot group). A headless character accepts a guildmate's invite by itself. None: your target. |
| `async raid_move(who: Spawn \| str, group: int \| None) -> CommandResult` | Put a raid member in raid group 0-11, or in no group (None), as dragging a name in the raid window (the raid leader's right). |
| `async raid_remove(who: Spawn \| str \| None = None) -> CommandResult` | Take a member out of the raid (the raid leader's right); None: leave the raid yourself. |
| `register_command(name: str, handler: Callable) -> None` | Add a slash command for DoCommand: handler(rest_of_line), sync or async. |
| `register_tlo(name: str, getter: Callable[[], Any]) -> None` | Add a Top-Level Object, read with bot.TLO(name). |
| `async retrieve_parcel(npc: Spawn \| int, parcel: "Parcel") -> CommandResult` | Take a parcel (Merchant.Parcels) from an open parcel merchant's window into your bags. |
| `async route_length(x: float, y: float, z: float \| None = None, timeout: float = 5) -> float \| None` | How far a walk to (in-game x, y, z) would be along the navmesh, without walking; None if there's no way there. A walk under way carries on. |
| `async route_path(x: float, y: float, z: float \| None = None, timeout: float = 5) -> list[tuple[float, float, float]] \| None` | The points of the walk to (in-game x, y, z) along the navmesh, in order (at most about 120), without walking; None if there's no way there. |
| `async run(plugins: list[MQPlugin] \| str \| None = None, frame_ms: int = 100) -> None` | Run plugins until the bot disconnects: on_load, then on_frame every frame, then on_clean. |
| `async say(text: str) -> CommandResult` |  |
| `async scribe(scroll: Item, book_slot: int \| None = None) -> CommandResult` | Scribe a spell scroll from your inventory into the spellbook, as the client: pick it up, write it into a free page. |
| `async sell(npc: Spawn \| int, item: Item \| int, quantity: int = 0) -> CommandResult` | Sell an item from your inventory (all of a stack by default) to an open merchant. |
| `async send_parcel(npc: Spawn \| int, item: Item \| int, to: str, note: str = , quantity: int = 0) -> CommandResult` | Send an item from your inventory (all of a stack by default) as a parcel to a character, at a parcel merchant whose window is open. Not no-drop items. The server allows one parcel every 30 seconds (Parcel:ParcelDeliveryDelay); a refusal comes as the merchant's tell. |
| `async sit(sit: bool = True) -> CommandResult` |  |
| `async spawn_bots(names: list[str], group: bool = True, pause: float = 1.5) -> list[Spawn]` | Spawn your EQEmu bots (^botspawn) and, by default, invite them so they follow you. |
| `async stand() -> CommandResult` |  |
| `async start(timeout: float = 60) -> None` | Connect, authenticate and wait for the first snapshot. |
| `async stop() -> CommandResult` | Stop walking. |
| `async stopcast() -> CommandResult` |  |
| `async surface(timeout: float = 30) -> MoveResult` | Under water: swim straight up to the surface for air (Me.Air: seconds left). The MoveResult when there, or REFUSED with why not (not under water, something solid above). |
| `async target(spawn: Spawn \| int \| None) -> CommandResult` | Target a spawn (or None to clear). The result means 'asked'; check bot.Target after. |
| `async tell(to: str, text: str) -> CommandResult` |  |
| `async use_item(item: Item \| int) -> CommandResult` | Right-click an item (or a slot): its click effect, a potion or food, or a tome, which teaches you its discipline. |
| `async wait_closed() -> None` |  |
| `wait_zoned(timeout: float = 90) -> "asyncio.Task[ZoneChange]"` | Wait for the next zone change to finish: ARRIVED or REFUSED ("TIMEOUT" if neither). |
| `walk_time(distance: float, margin: float = 30.0) -> float` | A timeout for walking `distance` units at your run speed: routes wind (half as far again as the straight line), plus `margin` seconds for doors, lifts and the start. With no speed known (rooted, or an older server) it assumes 10 units a second. |
| `async zone_plan(short_name: str, number: int = 0, timeout: float = 5) -> tuple[float, float] \| None` | The walk zone_to would take to this zone's zone line for a neighbouring zone, without walking: (its length, how much of it is a swim), or None if there's no way there. A walk under way carries on. |
| `async zone_to(short_name: str, timeout: float \| None = None, number: int = 0) -> ZoneChange` | Walk to this zone's zone line for a neighbouring zone (see Zone.Exits) and through it: the one with the shortest walk from here, or zone point `number` (a zone with several ways into another). |

### CommandResult

| Field | Type |
|---|---|
| `ok` | `bool` |
| `error` | `str` |

### Refused

The server refused the session (reason is the RefusedReason name).

### MQPlugin

| Property | |
|---|---|
| `name` |  |

| Method | |
|---|---|
| `async on_clean() -> None` | Called once when the bot stops running. |
| `async on_frame() -> None` | Called every frame while connected. Keep it quick; start tasks for long work. |
| `async on_load() -> None` | Called once before the first frame. |

### load_plugins

`load_plugins(directory: str, bot: "Bot") -> list[MQPlugin]`

Instantiate every MQPlugin subclass found in directory/*.py (files starting with _ are skipped).

## Top-level objects (TLOs)

### Me

| Field | Type |
|---|---|
| `ID` | `int` |
| `Name` | `str` |
| `Level` | `int` |
| `ClassID` | `int` |
| `RaceID` | `int` |
| `CurrentHPs` | `int` |
| `MaxHPs` | `int` |
| `CurrentMana` | `int` |
| `MaxMana` | `int` |
| `CurrentEndurance` | `int` |
| `MaxEndurance` | `int` |
| `X` | `float` |
| `Y` | `float` |
| `Z` | `float` |
| `Heading` | `float` |
| `TargetID` | `int` |
| `Sitting` | `bool` |
| `Combat` | `bool` |
| `CastingID` | `int` |
| `Gems` | `tuple` |
| `Buffs` | `tuple` |
| `Platinum` | `int` |
| `Gold` | `int` |
| `Silver` | `int` |
| `Copper` | `int` |
| `Haters` | `tuple` |
| `Weight` | `int` |
| `Capacity` | `int` |
| `RaceBit` | `int` |
| `ExpPct` | `float` |
| `AAExpPct` | `float` |
| `AAPoints` | `int` |
| `AASplit` | `int` |
| `RunSpeed` | `float` |
| `Disciplines` | `tuple` |
| `GameHour` | `int` |
| `Air` | `int` |
| `MaxAir` | `int` |
| `BankMoney` | `int` |
| `Gender` | `int` |
| `Resists` | `Resists` |
| `GearResists` | `Resists` |

| Property | |
|---|---|
| `Casting` |  |
| `Encumbered` |  |
| `Engaged` | In combat: some NPC has you on its hate list. |
| `Loc` |  |
| `Money` | All carried coin, in copper. |
| `Night` | EQ night, 21:00 to 7:00 (when the night spawns of Kithicor and others are up). |
| `PctEndurance` |  |
| `PctHPs` |  |
| `PctMana` |  |
| `Standing` |  |

| Method | |
|---|---|
| `Buff(name: str) -> Buff \| None` | Your buff whose name contains `name` (case-insensitive). |
| `Gem(n: int \| str) -> Gem \| None` | Gem n (1-based), or the gem holding a spell by name (case-insensitive). |
| `from_pb(m: pb.Self) -> "Me"` |  |

### Spawn

| Field | Type |
|---|---|
| `ID` | `int` |
| `Name` | `str` |
| `Type` | `str` |
| `Level` | `int` |
| `ClassID` | `int` |
| `RaceID` | `int` |
| `X` | `float` |
| `Y` | `float` |
| `Z` | `float` |
| `Heading` | `float` |
| `PctHPs` | `int` |
| `OwnerID` | `int` |
| `Headless` | `bool` |
| `TargetID` | `int` |
| `PctMana` | `int` |
| `Gender` | `int` |
| `Primary` | `int` |
| `Secondary` | `int` |
| `CastingID` | `int` |
| `Status` | `int` |
| `AggroRange` | `float` |
| `AssistRange` | `float` |
| `Aggro` | `int` |
| `Buffs` | `tuple` |
| `BotSkip` | `int` |
| `BotSkipType` | `int` |

| Property | |
|---|---|
| `AggrosGrey` | It aggros you even when you con grey to it (always-aggro, undead, or at the level the server's aggro rules ignore con from). |
| `Casting` |  |
| `Charmed` |  |
| `CleanName` |  |
| `Distance` | 2D distance from you, as MQ2's Spawn.Distance. |
| `Distance3D` |  |
| `Feared` |  |
| `KOS` | Hostile on sight to you (its faction toward you scowls): it attacks when it notices you, unless it cons grey to you and isn't one that aggros grey. |
| `Loc` |  |
| `MayAggro` | Its faction toward you is threatening: a quarter chance each time it looks. |
| `Mezzed` |  |
| `Rooted` |  |
| `Stunned` |  |

| Method | |
|---|---|
| `WillAggro(my_level: int, invisible: bool = False) -> bool` | It would aggro you if you came within AggroRange, by the server's rules as far as the spawn tells: hostile to you, not blind to you (invisible), and either not grey to you or one that aggros grey. A 'threatening' one is not counted (it is a chance, MayAggro). |
| `from_pb(s: pb.Spawn, me_x: float, me_y: float, me_z: float) -> "Spawn"` |  |

### Group

As MQ2's Group TLO. Member(0) is you; Members counts everyone else.

| Field | Type |
|---|---|
| `All` | `tuple[GroupMember, ...]` |

| Property | |
|---|---|
| `Leader` |  |
| `Members` |  |

| Method | |
|---|---|
| `Member(n: int \| str) -> GroupMember \| None` | Member(0) is you, Member(1..5) the others; or look one up by name. |
| `from_pb(m: pb.Self) -> "Group \| None"` |  |

### GroupMember

| Field | Type |
|---|---|
| `Name` | `str` |
| `ID` | `int` |
| `Leader` | `bool` |
| `Bot` | `bool` |
| `Buffs` | `tuple` |

### Raid

As MQ2's Raid TLO: everyone in the raid we are in, ourselves too.

| Field | Type |
|---|---|
| `All` | `tuple[RaidMember, ...]` |

| Property | |
|---|---|
| `Groups` | Each raid group in use (0-11) and its members; those in no group are left out (see Ungrouped). |
| `Leader` |  |
| `Members` |  |
| `Ungrouped` |  |

| Method | |
|---|---|
| `Group(n: int) -> tuple[RaidMember, ...]` | The members of raid group n (0-11), its leader first. |
| `Member(name: str) -> RaidMember \| None` |  |
| `from_pb(m: pb.Self) -> "Raid \| None"` |  |

### RaidMember

| Field | Type |
|---|---|
| `Name` | `str` |
| `ID` | `int` |
| `Group` | `int` |
| `GroupLeader` | `bool` |
| `RaidLeader` | `bool` |
| `Bot` | `bool` |
| `Class` | `int` |
| `Level` | `int` |

### Zone

| Field | Type |
|---|---|
| `ID` | `int` |
| `InstanceID` | `int` |
| `ShortName` | `str` |
| `Name` | `str` |
| `Exits` | `tuple` |

| Method | |
|---|---|
| `Exit(short_name: str) -> "ZoneExit \| None"` |  |
| `from_pb(z: pb.ZoneInfo) -> "Zone"` |  |

### ZoneExit

| Field | Type |
|---|---|
| `Zone` | `str` |
| `ZoneID` | `int` |
| `X` | `float` |
| `Y` | `float` |
| `Z` | `float` |

## What you carry and cast

### Item

| Field | Type |
|---|---|
| `Slot` | `int` |
| `ID` | `int` |
| `Name` | `str` |
| `Charges` | `int` |
| `Container` | `bool` |
| `AC` | `int` |
| `HP` | `int` |
| `Mana` | `int` |
| `Endurance` | `int` |
| `STR` | `int` |
| `STA` | `int` |
| `AGI` | `int` |
| `DEX` | `int` |
| `WIS` | `int` |
| `INT` | `int` |
| `CHA` | `int` |
| `Damage` | `int` |
| `Delay` | `int` |
| `Slots` | `int` |
| `ReqLevel` | `int` |
| `Weight` | `float` |
| `Price` | `int` |
| `NoDrop` | `bool` |
| `Lore` | `bool` |
| `Magic` | `bool` |
| `BagSlots` | `int` |
| `BagSize` | `int` |
| `ItemType` | `int` |
| `Usable` | `bool` |
| `Classes` | `int` |
| `Races` | `int` |
| `ScrollSpell` | `int` |
| `ScrollLevel` | `int` |
| `BagWR` | `int` |
| `BagType` | `int` |
| `AugType` | `int` |
| `AugRestrict` | `int` |
| `AugDistiller` | `int` |
| `AugSockets` | `tuple` |
| `Augs` | `tuple` |

| Property | |
|---|---|
| `Banked` |  |
| `IsAugment` |  |
| `StorageBag` | A container for carrying things (a bag, pouch, backpack, chest, quiver), not a tradeskill one. |
| `Worn` |  |

| Method | |
|---|---|
| `Fits(slot: int) -> bool` | Can it be worn in this slot? Never an augment: its slots are the items it goes into, not where it's worn (no client equips one; the guild's leaders and bots wore Bluegreen Rocks on their fingers until 9 Nov). |
| `FreeSockets() -> list[int]` | Indexes (0-5) of the sockets with nothing in them. |
| `UsableBy(class_id: int, race_bit: int, level: int) -> bool` | Whether someone of this class, race and level could wear it. |
| `from_pb(i: pb.Item) -> "Item"` |  |

### Buff

| Field | Type |
|---|---|
| `ID` | `int` |
| `Name` | `str` |
| `Ticks` | `int` |
| `Slot` | `int` |

| Property | |
|---|---|
| `Duration` | Seconds left (inf if permanent). |

### Gem

| Field | Type |
|---|---|
| `Slot` | `int` |
| `ID` | `int` |
| `Name` | `str` |
| `Ready` | `bool` |

### BookSpell

| Field | Type |
|---|---|
| `ID` | `int` |
| `Name` | `str` |
| `Level` | `int` |
| `Slot` | `int` |

### Resists

Resists now (base, gear, buffs, AAs), as the inventory window shows them.

| Field | Type |
|---|---|
| `Magic` | `int` |
| `Cold` | `int` |
| `Fire` | `int` |
| `Poison` | `int` |
| `Disease` | `int` |

| Method | |
|---|---|
| `from_pb(r: pb.Resists) -> "Resists"` |  |

### BotGear

One of your EQEmu bots and what it wears (Item.Slot is the worn slot).

| Field | Type |
|---|---|
| `ID` | `int` |
| `Name` | `str` |
| `ClassID` | `int` |
| `RaceID` | `int` |
| `Level` | `int` |
| `RaceBit` | `int` |
| `Equipment` | `tuple` |
| `Resists` | `Resists` |
| `Buffs` | `tuple` |
| `GearResists` | `Resists` |

| Method | |
|---|---|
| `Worn(slot: int) -> "Item \| None"` |  |
| `from_pb(b: pb.BotGear) -> "BotGear"` |  |

### PackItem

Something one of your bots carries in its pack (Bot.pack_list): its slot there, the item, how many,
and whether it's a bag (the bags hold the rest).

| Field | Type |
|---|---|
| `Slot` | `int` |
| `ID` | `int` |
| `Count` | `int` |
| `Name` | `str` |
| `Bag` | `bool` |

## Results and events

### MoveResult

How a /moveto ended: "ARRIVED", "STOPPED", "STUCK", "NO_PATH", "ZONE_LINE", "LOCKED" (a door
on the way that it has no key for) or "REFUSED" (the server didn't take the command: Error says
why, e.g. the rate limit, casting, or not being in a zone yet).

| Field | Type |
|---|---|
| `Status` | `str` |
| `X` | `float` |
| `Y` | `float` |
| `Z` | `float` |
| `Error` | `str` |
| `Nav` | `tuple[NavNote, ...]` |

| Property | |
|---|---|
| `Loc` |  |

### NavNote

Where a walk found the zone's navmesh wanting (MoveResult.Nav). Kind: "no_mesh_here" (none
where we stood), "no_mesh_there" (none at the destination), "not_connected" (no way between:
Closest is where it gets nearest), "stuck" (walked into something it says isn't there), or a gap
the walk went round: "off_mesh", "straight_walk" (To: where it stepped or walked to); and doors it
couldn't open: "locked", "door_wont_open".
Points are (x, y, z).

| Field | Type |
|---|---|
| `Kind` | `str` |
| `At` | `tuple[float, float, float]` |
| `To` | `tuple[float, float, float]` |
| `Closest` | `tuple[float, float, float]` |

### LootResult

| Field | Type |
|---|---|
| `CorpseID` | `int` |
| `ok` | `bool` |
| `Error` | `str` |
| `Items` | `tuple` |
| `Platinum` | `int` |
| `Gold` | `int` |
| `Silver` | `int` |
| `Copper` | `int` |
| `Left` | `tuple` |

### Merchant

An open merchant window: what it sells (Item.Slot is the merchant slot, Item.Price the cost).
A parcel merchant also lists the parcels waiting for you.

| Field | Type |
|---|---|
| `NpcID` | `int` |
| `Items` | `tuple` |
| `ParcelMerchant` | `bool` |
| `Parcels` | `tuple` |

| Method | |
|---|---|
| `Find(name: str) -> "Item \| None"` |  |

### Parcel

A parcel waiting for you at the parcel merchants (any of them). ItemID 99990 is coin
(Quantity: copper).

| Field | Type |
|---|---|
| `Slot` | `int` |
| `ItemID` | `int` |
| `Name` | `str` |
| `Quantity` | `int` |
| `From` | `str` |
| `Note` | `str` |
| `Sent` | `int` |

### Consider

A /consider answer. Color is "green", "lightblue", "blue", "white", "yellow", "red" or "grey".

| Field | Type |
|---|---|
| `SpawnID` | `int` |
| `Color` | `str` |
| `Faction` | `str` |
| `PctHPs` | `int` |

| Property | |
|---|---|
| `Safe` | An easy fight: green, light blue or blue. |

### Death

| Field | Type |
|---|---|
| `Killer` | `str` |
| `CorpseID` | `int` |
| `SpellID` | `int` |
| `Damage` | `int` |

### SkillUp

A skill (or language: SkillID 100 and up) went up to Value.

| Field | Type |
|---|---|
| `SkillID` | `int` |
| `Name` | `str` |
| `Value` | `int` |

| Property | |
|---|---|
| `Line` | What the client prints for it. |

### ZoneChange

A zone change: "LEAVING" (on the way), "ARRIVED" (in Zone, state is fresh) or "REFUSED".

| Field | Type |
|---|---|
| `Status` | `str` |
| `Zone` | `str` |
| `ZoneID` | `int` |
| `Detail` | `str` |

### Chat

| Field | Type |
|---|---|
| `Channel` | `str` |
| `From` | `str` |
| `To` | `str` |
| `Text` | `str` |
| `Line` | `str` |

### Message

| Field | Type |
|---|---|
| `Type` | `int` |
| `Line` | `str` |
| `StringID` | `int` |

## Slash commands

`await bot.DoCommand(line)` runs these, MacroQuest-style; a plugin adds its own with `bot.register_command(name, handler)`. GM commands are said: `/say #zone qeynos` (if the account's status allows them). EQEmu bot commands go through `/bot`: `/bot follow` is said as `^follow`.

`/attack`, `/auc`, `/auction`, `/bot`, `/cast`, `/con`, `/consider`, `/disband`, `/disc`, `/discipline`, `/doability`, `/face`, `/g`, `/gsay`, `/gu`, `/guildsay`, `/invite`, `/loot`, `/memspell`, `/moveto`, `/msg`, `/ooc`, `/pet`, `/rsay`, `/s`, `/say`, `/shout`, `/sit`, `/stand`, `/stopcast`, `/t`, `/target`, `/tell`, `/travelto`, `/zoneto`

## Constants

| Name | Value |
|---|---|
| `ABILITIES` | `{'backstab': 8, 'bash': 10, 'slam': 10, 'dragon punch': 21, 'tail rake': 21, ...` |
| `BAG_SLOTS_BEGIN` | `4010` |
| `BANK_BAGS_BEGIN` | `6210` |
| `BANK_SLOTS` | `(2000, 2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009, 2010, 2011, 2012...` |
| `BOT_SKIPS` | `{0: '', 1: 'incapacitated', 2: 'held', 3: 'catching up', 4: 'no mana', 5: 'ou...` |
| `CHAT_AUCTION` | `4` |
| `CHAT_GROUP` | `2` |
| `CHAT_GUILD` | `0` |
| `CHAT_OOC` | `5` |
| `CHAT_RAID` | `15` |
| `CHAT_SAY` | `8` |
| `CHAT_SHOUT` | `3` |
| `CHAT_TELL` | `7` |
| `CURSOR_SLOT` | `33` |
| `GENERAL_SLOTS` | `(23, 24, 25, 26, 27, 28, 29, 30, 31, 32)` |
| `PET_COMMANDS` | `{'health': 0, 'leader': 1, 'attack': 2, 'qattack': 3, 'follow': 4, 'guard': 5...` |
| `RAID_GROUPLESS` | `4294967295` |
| `SDK_VERSION` | `'eqmq/0.21'` |
| `WORLD_CONTAINER` | `1000` |
| `WORLD_SLOT` | `4000` |
| `WORN_SLOTS` | `{'charm': 0, 'ear1': 1, 'head': 2, 'face': 3, 'ear2': 4, 'neck': 5, 'shoulder...` |
