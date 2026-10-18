"""A subset of MQ2's spawn search syntax, e.g. Spawn("npc radius 50 orc").

Supported: pc, npc, pet, bot, corpse, headless, id <n>, radius <n>, zradius <n>,
range <min> <max> (levels), and remaining words as a case-insensitive name match.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .tlo import Spawn

_TYPES = {"pc": "PC", "npc": "NPC", "pet": "Pet", "bot": "Bot", "corpse": "Corpse"}


@dataclass
class SpawnSearch:
    types: set[str] = field(default_factory=set)
    spawn_id: int | None = None
    radius: float | None = None
    zradius: float | None = None
    level_min: int | None = None
    level_max: int | None = None
    headless: bool = False
    name: str = ""

    @staticmethod
    def parse(text: str) -> "SpawnSearch":
        q = SpawnSearch()
        words = text.split()
        names: list[str] = []
        i = 0

        def number(kind):
            nonlocal i
            if i + 1 >= len(words):
                raise ValueError(f"'{words[i]}' needs a number")
            i += 1
            return kind(words[i])

        while i < len(words):
            w = words[i].lower()
            if w in _TYPES:
                q.types.add(_TYPES[w])
            elif w == "headless":
                q.headless = True
            elif w == "id":
                q.spawn_id = number(int)
            elif w == "radius":
                q.radius = number(float)
            elif w == "zradius":
                q.zradius = number(float)
            elif w == "range":
                q.level_min = number(int)
                q.level_max = number(int)
            else:
                names.append(words[i])
            i += 1

        q.name = " ".join(names).lower()
        return q

    def matches(self, s: Spawn, me_z: float) -> bool:
        if self.types and s.Type not in self.types:
            return False
        if self.spawn_id is not None and s.ID != self.spawn_id:
            return False
        if self.headless and not s.Headless:
            return False
        if self.radius is not None and s.Distance > self.radius:
            return False
        if self.zradius is not None and abs(s.Z - me_z) > self.zradius:
            return False
        if self.level_min is not None and not (self.level_min <= s.Level <= self.level_max):
            return False
        if self.name and self.name not in s.Name.lower():
            return False
        return True
