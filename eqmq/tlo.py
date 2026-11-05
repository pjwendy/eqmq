"""MQ2-style Top-Level Objects: frozen, read-only views of game state.

Names follow MacroQuest (vocabulary only, no MQ2 code). Coordinates are in-game: Loc prints
"Y, X, Z" the way /loc does.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .proto import headless_pb2 as pb

_SPAWN_TYPES = {
    pb.SPAWN_TYPE_PLAYER: "PC",
    pb.SPAWN_TYPE_NPC: "NPC",
    pb.SPAWN_TYPE_BOT: "Bot",
    pb.SPAWN_TYPE_PLAYER_CORPSE: "Corpse",
    pb.SPAWN_TYPE_NPC_CORPSE: "Corpse",
}


def _pct(cur: int, mx: int) -> int:
    return int(cur * 100 / mx) if mx > 0 else 0


# con colours and faction standings, as the client names them
CON_COLORS = {2: "green", 4: "blue", 6: "grey", 10: "white", 13: "red", 15: "yellow", 18: "lightblue", 20: "white"}
FACTIONS = {1: "ally", 2: "warmly", 3: "kindly", 4: "amiable", 5: "indifferent", 6: "apprehensive",
            7: "dubious", 8: "threatening", 9: "scowls"}


@dataclass(frozen=True)
class Gem:
    Slot: int        # 1-based, as /cast 1 and MQ2's Me.Gem[1]
    ID: int
    Name: str
    Ready: bool      # not refreshing, not casting, not memorising


@dataclass(frozen=True)
class Buff:
    ID: int
    Name: str
    Ticks: int       # 6-second ticks left; -1 permanent

    @property
    def Duration(self) -> float:
        """Seconds left (inf if permanent)."""
        return math.inf if self.Ticks < 0 else self.Ticks * 6.0


@dataclass(frozen=True)
class BookSpell:
    ID: int
    Name: str
    Level: int
    Slot: int = 0  # its page in the book


# EQ inventory slots (RoF2 numbering, as the server uses)
WORN_SLOTS = {"charm": 0, "ear1": 1, "head": 2, "face": 3, "ear2": 4, "neck": 5, "shoulders": 6, "arms": 7,
              "back": 8, "wrist1": 9, "wrist2": 10, "range": 11, "hands": 12, "primary": 13, "secondary": 14,
              "finger1": 15, "finger2": 16, "chest": 17, "legs": 18, "feet": 19, "waist": 20, "powersource": 21,
              "ammo": 22}
GENERAL_SLOTS = tuple(range(23, 33))  # the ten top-level bag slots
CURSOR_SLOT = 33
WORLD_SLOT = 4000        # the first slot of a world container (a forge, an oven): its items go to WORLD_SLOT + 0 ...
WORLD_CONTAINER = 1000   # combine()'s container_slot for the world container opened
BAG_SLOTS_BEGIN = 4010                 # general bag contents: 4010 + (general slot - 23) * 200 + index
BANK_SLOTS = tuple(range(2000, 2024))  # the bank's 24 slots (use them next to a banker)
BANK_BAGS_BEGIN = 6210                 # bank bag contents: 6210 + (bank slot - 2000) * 200 + index
# (the server's numbering: 200 per bag; carried bags 4010-6009, the cursor's bag 6010-6209)


@dataclass(frozen=True)
class Item:
    Slot: int
    ID: int
    Name: str
    Charges: int
    Container: bool
    AC: int = 0
    HP: int = 0
    Mana: int = 0
    Endurance: int = 0
    STR: int = 0
    STA: int = 0
    AGI: int = 0
    DEX: int = 0
    WIS: int = 0
    INT: int = 0
    CHA: int = 0
    Damage: int = 0
    Delay: int = 0
    Slots: int = 0        # bitmask of worn slots it fits
    ReqLevel: int = 0
    Weight: float = 0.0
    Price: int = 0        # copper: its value, or for a merchant's item what it costs
    NoDrop: bool = False
    Lore: bool = False
    Magic: bool = False
    BagSlots: int = 0
    BagSize: int = 0
    ItemType: int = 0
    Usable: bool = False  # its holder (you, or the bot wearing it) can wear it at its level
    Classes: int = 0      # bitmask: bit (class - 1)
    Races: int = 0        # bitmask of EQ race bits (see RaceBit on Me / BotGear)
    ScrollSpell: int = 0  # a spell scroll: the spell it teaches
    ScrollLevel: int = 0  # ... the level your class learns it (0: not your class)
    BagWR: int = 0        # containers: weight reduction, percent
    BagType: int = 0      # containers: EQ bag type (0-8 storage; 9 and up tradeskill: mixing bowl, forge...)

    @property
    def StorageBag(self) -> bool:
        """A container for carrying things (a bag, pouch, backpack, chest, quiver), not a tradeskill one."""
        return self.Container and self.BagType <= 8

    @property
    def Banked(self) -> bool:
        return 2000 <= self.Slot <= 2023 or BANK_BAGS_BEGIN <= self.Slot < BANK_BAGS_BEGIN + 24 * 200

    def UsableBy(self, class_id: int, race_bit: int, level: int) -> bool:
        """Whether someone of this class, race and level could wear it."""
        return bool(self.Slots) and bool(self.Classes & (1 << (class_id - 1))) and             bool(self.Races & race_bit) and self.ReqLevel <= level

    @property
    def Worn(self) -> bool:
        return 0 <= self.Slot <= 22

    def Fits(self, slot: int) -> bool:
        return bool(self.Slots & (1 << slot))

    @staticmethod
    def from_pb(i: pb.Item) -> "Item":
        return Item(i.slot, i.item_id, i.name, i.charges, i.container, i.ac, i.hp, i.mana, i.endurance, i.str,
                    i.sta, i.agi, i.dex, i.wis, getattr(i, "int"), i.cha, i.damage, i.delay, i.slots, i.req_level,
                    i.weight, i.price, i.no_drop, i.lore, i.magic, i.bag_slots, i.bag_size, i.item_type, i.usable,
                    i.classes, i.races, i.scroll_spell, i.scroll_level, i.bag_wr, i.bag_type)


@dataclass(frozen=True)
class BotGear:
    """One of your EQEmu bots and what it wears (Item.Slot is the worn slot)."""
    ID: int
    Name: str
    ClassID: int
    RaceID: int
    Level: int
    RaceBit: int
    Equipment: tuple = ()

    def Worn(self, slot: int) -> "Item | None":
        return next((i for i in self.Equipment if i.Slot == slot), None)

    @staticmethod
    def from_pb(b: pb.BotGear) -> "BotGear":
        return BotGear(b.spawn_id, b.name, b.class_id, b.race_id, b.level, b.race_bit,
                       tuple(Item.from_pb(i) for i in b.equipment))


@dataclass(frozen=True)
class Spawn:
    ID: int
    Name: str
    Type: str          # "PC", "NPC", "Pet", "Bot", "Corpse"
    Level: int
    ClassID: int
    RaceID: int
    X: float
    Y: float
    Z: float
    Heading: float
    PctHPs: int
    OwnerID: int
    Headless: bool
    TargetID: int = 0  # who it has targeted; for an NPC in combat, who it's hitting
    PctMana: int = 0   # 0 for spawns without mana
    Gender: int = 0    # 0 male, 1 female, 2 neutral (the model to draw)
    Primary: int = 0   # the model of what it holds in its primary hand (IT<n>), 0 if none
    Secondary: int = 0
    CastingID: int = 0  # the spell it is casting, 0 if none
    Status: int = 0     # bits: 1 mezzed, 2 rooted, 4 stunned, 8 feared or fleeing, 16 charmed
    AggroRange: float = 0.0   # an NPC: the radius it notices you in (0: it never aggros)
    AssistRange: float = 0.0  # an NPC: the radius in which it calls others to help
    Aggro: int = 0            # an NPC with an aggro range: bits 1 hostile on sight (KOS), 2 may aggro (threatening), 4 aggros even a character it cons grey to
    Buffs: tuple = ()         # an NPC that is fighting (or has us on its hate list): the spells on it (Buff), our slows, roots, mezzes and damage over time
    _me_x: float = 0.0
    _me_y: float = 0.0
    _me_z: float = 0.0

    @property
    def CleanName(self) -> str:
        return self.Name

    @property
    def Casting(self) -> bool:
        return self.CastingID != 0

    @property
    def Mezzed(self) -> bool:
        return bool(self.Status & 1)

    @property
    def Rooted(self) -> bool:
        return bool(self.Status & 2)

    @property
    def Stunned(self) -> bool:
        return bool(self.Status & 4)

    @property
    def Feared(self) -> bool:
        return bool(self.Status & 8)

    @property
    def Charmed(self) -> bool:
        return bool(self.Status & 16)

    @property
    def KOS(self) -> bool:
        """Hostile on sight to you (its faction toward you scowls): it attacks when it notices you, unless it cons grey to you and isn't one that aggros grey."""
        return bool(self.Aggro & 1)

    @property
    def MayAggro(self) -> bool:
        """Its faction toward you is threatening: a quarter chance each time it looks."""
        return bool(self.Aggro & 2)

    @property
    def AggrosGrey(self) -> bool:
        """It aggros you even when you con grey to it (always-aggro, undead, or at the level the server's aggro rules ignore con from)."""
        return bool(self.Aggro & 4)

    def WillAggro(self, my_level: int, invisible: bool = False) -> bool:
        """It would aggro you if you came within AggroRange, by the server's rules as far as the spawn tells: hostile to you, not blind to you
        (invisible), and either not grey to you or one that aggros grey. A 'threatening' one is not counted (it is a chance, MayAggro)."""
        if invisible or not (self.Aggro & 1) or self.AggroRange <= 0:
            return False
        grey = my_level > 15 and self.Level <= my_level - int((my_level + 5) / 3) or (my_level <= 15 and self.Level - my_level <= -6)
        return not grey or self.AggrosGrey

    @property
    def Loc(self) -> str:
        return f"{self.Y:.2f}, {self.X:.2f}, {self.Z:.2f}"

    @property
    def Distance(self) -> float:
        """2D distance from you, as MQ2's Spawn.Distance."""
        return math.hypot(self.X - self._me_x, self.Y - self._me_y)

    @property
    def Distance3D(self) -> float:
        return math.dist((self.X, self.Y, self.Z), (self._me_x, self._me_y, self._me_z))

    @staticmethod
    def from_pb(s: pb.Spawn, me_x: float, me_y: float, me_z: float) -> "Spawn":
        type_name = _SPAWN_TYPES.get(s.type, "Unknown")
        if type_name == "NPC" and s.owner_id:
            type_name = "Pet"
        return Spawn(
            ID=s.id, Name=s.name, Type=type_name, Level=s.level, ClassID=s.class_id,
            RaceID=s.race_id, X=s.x, Y=s.y, Z=s.z, Heading=s.heading, PctHPs=s.hp_pct,
            OwnerID=s.owner_id, Headless=s.headless, TargetID=s.target_id, PctMana=s.mana_pct, Gender=s.gender, Primary=s.primary, Secondary=s.secondary, CastingID=s.casting_spell_id, Status=s.status, AggroRange=s.aggro_range, AssistRange=s.assist_range, Aggro=s.aggro, Buffs=tuple(Buff(b.spell_id, b.name, b.ticks) for b in s.buffs), _me_x=me_x, _me_y=me_y, _me_z=me_z,
        )


@dataclass(frozen=True)
class Me:
    ID: int
    Name: str
    Level: int
    ClassID: int
    RaceID: int
    CurrentHPs: int
    MaxHPs: int
    CurrentMana: int
    MaxMana: int
    CurrentEndurance: int
    MaxEndurance: int
    X: float
    Y: float
    Z: float
    Heading: float
    TargetID: int
    Sitting: bool
    Combat: bool       # auto-attack on
    CastingID: int     # 0 if not casting
    Gems: tuple = ()   # Gem, by slot
    Buffs: tuple = ()  # Buff
    Platinum: int = 0
    Gold: int = 0
    Silver: int = 0
    Copper: int = 0
    Haters: tuple = ()  # spawn ids of NPCs with you on their hate list
    Weight: int = 0     # carried weight
    Capacity: int = 0   # carry more than this (your STR) and you're encumbered
    RaceBit: int = 0    # your bit in Item.Races
    ExpPct: float = 0.0     # progress through your level, 0-100 (MQ2 Me.PctExp)
    AAExpPct: float = 0.0   # progress to your next AA point, 0-100 (MQ2 Me.PctAAExp)
    AAPoints: int = 0       # unspent AA points
    AASplit: int = 0        # share of experience going to AA, 0-100
    RunSpeed: float = 0.0   # how fast a walk goes now, units per second (0: rooted, or an older server)
    Disciplines: tuple = () # spell ids of the disciplines you know (bot.discipline())
    GameHour: int = 0       # the zone's EQ hour, 1-24 (0: an older server); an EQ hour is 3 real minutes
    Air: int = 0            # seconds of air left under water (full whenever you can breathe; at none you drown)
    MaxAir: int = 0         # seconds of air at most (Stamina, Lung Capacity)
    BankMoney: int = 0      # the coin in our bank, in copper (bot.bank_coin moves it, beside a banker)
    Gender: int = 0         # 0 male, 1 female, 2 neutral

    @property
    def Night(self) -> bool:
        """EQ night, 21:00 to 7:00 (when the night spawns of Kithicor and others are up)."""
        return bool(self.GameHour) and (self.GameHour >= 21 or self.GameHour < 7)

    @property
    def PctHPs(self) -> int:
        return _pct(self.CurrentHPs, self.MaxHPs)

    @property
    def PctMana(self) -> int:
        return _pct(self.CurrentMana, self.MaxMana)

    @property
    def PctEndurance(self) -> int:
        return _pct(self.CurrentEndurance, self.MaxEndurance)

    @property
    def Standing(self) -> bool:
        return not self.Sitting

    @property
    def Casting(self) -> bool:
        return self.CastingID != 0

    def Gem(self, n: int | str) -> Gem | None:
        """Gem n (1-based), or the gem holding a spell by name (case-insensitive)."""
        for g in self.Gems:
            if (isinstance(n, int) and g.Slot == n) or (isinstance(n, str) and g.Name.lower() == n.lower()):
                return g
        return None

    def Buff(self, name: str) -> Buff | None:
        """Your buff whose name contains `name` (case-insensitive)."""
        return next((b for b in self.Buffs if name.lower() in b.Name.lower()), None)

    @property
    def Encumbered(self) -> bool:
        return self.Capacity > 0 and self.Weight > self.Capacity

    @property
    def Engaged(self) -> bool:
        """In combat: some NPC has you on its hate list."""
        return bool(self.Haters)

    @property
    def Money(self) -> int:
        """All carried coin, in copper."""
        return ((self.Platinum * 10 + self.Gold) * 10 + self.Silver) * 10 + self.Copper

    @property
    def Loc(self) -> str:
        return f"{self.Y:.2f}, {self.X:.2f}, {self.Z:.2f}"

    @staticmethod
    def from_pb(m: pb.Self) -> "Me":
        return Me(
            ID=m.spawn_id, Name=m.name, Level=m.level, ClassID=m.class_id, RaceID=m.race_id, Gender=m.gender,
            CurrentHPs=m.hp, MaxHPs=m.max_hp, CurrentMana=m.mana, MaxMana=m.max_mana,
            CurrentEndurance=m.endurance, MaxEndurance=m.max_endurance, X=m.x, Y=m.y, Z=m.z,
            Heading=m.heading, TargetID=m.target_id, Sitting=m.sitting, Combat=m.auto_attack,
            CastingID=m.casting_spell_id,
            Gems=tuple(Gem(g.slot + 1, g.spell_id, g.name, g.ready) for g in m.gems),
            Buffs=tuple(Buff(b.spell_id, b.name, b.ticks) for b in m.buffs),
            Platinum=m.platinum, Gold=m.gold, Silver=m.silver, Copper=m.copper, Haters=tuple(m.haters),
            Weight=m.weight, Capacity=m.capacity, RaceBit=m.race_bit,
            ExpPct=m.exp_pct, AAExpPct=m.aa_exp_pct, AAPoints=m.aa_points, AASplit=m.aa_split, RunSpeed=m.run_speed,
            Disciplines=tuple(m.disciplines), GameHour=m.game_hour, Air=m.air, MaxAir=m.max_air, BankMoney=m.bank_copper,
        )


@dataclass(frozen=True)
class GroupMember:
    Name: str
    ID: int          # spawn id, 0 if not in this zone
    Leader: bool
    Bot: bool        # an EQEmu bot
    Buffs: tuple = ()  # Buff, what is on them now (their own are Me.Buffs)


@dataclass(frozen=True)
class Group:
    """As MQ2's Group TLO. Member(0) is you; Members counts everyone else."""
    All: tuple[GroupMember, ...]
    _me: str = ""

    @property
    def Members(self) -> int:
        return max(0, len(self.All) - 1)

    @property
    def Leader(self) -> GroupMember | None:
        return next((m for m in self.All if m.Leader), None)

    def Member(self, n: int | str) -> GroupMember | None:
        """Member(0) is you, Member(1..5) the others; or look one up by name."""
        if isinstance(n, str):
            return next((m for m in self.All if m.Name.lower() == n.lower()), None)
        others = [m for m in self.All if m.Name != self._me]
        me = [m for m in self.All if m.Name == self._me]
        ordered = me + others
        return ordered[n] if 0 <= n < len(ordered) else None

    @staticmethod
    def from_pb(m: pb.Self) -> "Group | None":
        if not m.group:
            return None
        return Group(tuple(GroupMember(g.name, g.spawn_id, g.leader, g.bot, tuple(Buff(b.spell_id, b.name, b.ticks) for b in g.buffs)) for g in m.group), _me=m.name)


@dataclass(frozen=True)
class ZoneExit:
    Zone: str          # short name of the zone it leads to
    ZoneID: int
    X: float           # where the zone line is; +-999999 means "anywhere along this axis"
    Y: float
    Z: float


@dataclass(frozen=True)
class Zone:
    ID: int
    InstanceID: int
    ShortName: str
    Name: str          # long name, as MQ2's Zone.Name
    Exits: tuple = ()  # ZoneExit, one per neighbouring zone

    def Exit(self, short_name: str) -> "ZoneExit | None":
        return next((e for e in self.Exits if e.Zone.lower() == short_name.lower()), None)

    @staticmethod
    def from_pb(z: pb.ZoneInfo) -> "Zone":
        return Zone(ID=z.id, InstanceID=z.instance_id, ShortName=z.short_name, Name=z.long_name,
                    Exits=tuple(ZoneExit(e.zone, e.zone_id, e.x, e.y, e.z) for e in z.exits))
