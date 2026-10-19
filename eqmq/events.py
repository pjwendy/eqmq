"""Game text and MQ2-style #event matching.

Chat and server messages are rendered as the EQ client prints them, so MQ2 patterns such as
"#1# tells you, '#2#'" work unchanged. In a pattern, #*# matches anything and #1#..#9#
capture, as in MQ2's #event.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .eqstr import EqStr
from .proto import headless_pb2 as pb

_CHAT_VERBS = {
    pb.CHAT_SAY: "says",
    pb.CHAT_SHOUT: "shouts",
    pb.CHAT_OOC: "says out of character",
    pb.CHAT_AUCTION: "auctions",
    pb.CHAT_GROUP: "tells the group",
    pb.CHAT_GUILD: "tells the guild",
    pb.CHAT_RAID: "tells the raid",
    pb.CHAT_TELL: "tells you",
}


@dataclass(frozen=True)
class Chat:
    Channel: str      # "SAY", "TELL", "GROUP", ...
    From: str
    To: str
    Text: str
    Line: str         # as the client prints it


@dataclass(frozen=True)
class Message:
    Type: int         # chat colour / message type
    Line: str
    StringID: int = 0


def render_chat(c: pb.ChatMessage) -> Chat:
    channel = pb.ChatChannel.Name(c.channel).removeprefix("CHAT_") if c.channel in pb.ChatChannel.values() else str(c.channel)
    sender = getattr(c, "from")  # "from" is a Python keyword, so no attribute access
    if c.channel == pb.CHAT_TELL_ECHO:
        line = f"You told {c.to}, '{c.text}'"
    else:
        line = f"{sender} {_CHAT_VERBS.get(c.channel, 'says')}, '{c.text}'"
    return Chat(Channel=channel, From=sender, To=c.to, Text=strip_links(c.text), Line=strip_links(line))


# EQ links (items, say links):  + a 56-character hex link body + the visible text + .
# Some arrive without the  markers once rendered from eqstr.
_LINK = re.compile(r"[0-9A-F]{56}(.*?)|(?<![0-9A-Za-z])[0-9A-F]{56}(?=[A-Z])")


def strip_links(text: str) -> str:
    """Game text as the client shows it: links reduced to their visible text."""
    if "" not in text and len(text) < 56:
        return text
    return _LINK.sub(lambda m: m.group(1) or "", text).replace("", "")


def render_message(m: pb.ServerMessage, eqstr: EqStr) -> Message:
    if m.string_id:
        return Message(Type=m.type, Line=strip_links(eqstr.format(m.string_id, [strip_links(a) for a in m.args])),
                       StringID=m.string_id)
    text, sayer = strip_links(m.text), m.sayer
    if not sayer or m.speak_mode in (0, 3):
        line = text
    elif m.speak_mode == 2:
        line = f"{sayer} shouts, '{text}'"
    elif m.speak_mode == 4:
        line = f"{sayer}{text}" if text[:1] in ("\\", "@") else f"{sayer} {text}"
    elif m.speak_mode == 5:
        line = f"{sayer} tells the group, '{text}'"
    else:
        line = f"{sayer} says, '{text}'"
    return Message(Type=m.type, Line=line)


class EventPattern:
    """Compile an MQ2 #event pattern into a regex over a whole line."""

    def __init__(self, pattern: str):
        self.pattern = pattern
        parts = re.split(r"(#\*#|#[1-9]#)", pattern)
        regex = ""
        self.groups: list[int] = []
        for p in parts:
            if p == "#*#":
                regex += ".*?"
            elif re.fullmatch(r"#[1-9]#", p):
                self.groups.append(int(p[1]))
                regex += "(.*?)"
            else:
                regex += re.escape(p)
        self.regex = re.compile(f"^{regex}$", re.DOTALL)

    def match(self, line: str) -> list[str] | None:
        m = self.regex.match(line)
        if not m:
            return None
        # captures in #n# order, like MQ2's Param1..Param9
        by_number = dict(zip(self.groups, m.groups()))
        return [by_number[n] for n in sorted(by_number)]
