"""Client string table (eqstr_us.txt), used to render server messages sent as string ids.

The file belongs to the EverQuest client; the SDK never ships it. Point the Bot at your
client's copy, e.g. eqstr="C:/EQ/RoF2Client/eqstr_us.txt", or set EQMQ_EQSTR.
"""
from __future__ import annotations

import os
import re

_PLACEHOLDER = re.compile(r"%(T?)(\d)")  # %2: the second argument; %T2: the second argument is the id of another string (a merchant's greeting: "Caden Zharik says '%T2'")


class EqStr:
    def __init__(self, strings: dict[int, str] | None = None):
        self.strings = strings or {}

    @staticmethod
    def load(path: str | None) -> "EqStr":
        path = path or os.environ.get("EQMQ_EQSTR")
        if not path or not os.path.exists(path):
            return EqStr()
        strings: dict[int, str] = {}
        with open(path, encoding="latin-1") as f:
            for i, line in enumerate(f):
                if i < 2:  # "EQST0002" header and the count line
                    continue
                sid, _, text = line.rstrip("\r\n").partition(" ")
                if sid.isdigit():
                    strings[int(sid)] = text
        return EqStr(strings)

    def format(self, string_id: int, args: list[str]) -> str:
        template = self.strings.get(string_id)
        if template is None:
            return f"[eqstr {string_id}] " + " ".join(args) if args else f"[eqstr {string_id}]"

        def sub(m: re.Match) -> str:
            n = int(m.group(2)) - 1
            value = args[n] if 0 <= n < len(args) else ""
            if m.group(1) and value.isdigit() and int(value) in self.strings:  # (another string, with the arguments after this one)
                return self.format(int(value), args[n + 1:])
            return value

        return _PLACEHOLDER.sub(sub, template)
