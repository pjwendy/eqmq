#!/usr/bin/env python3
"""Writes docs/reference.md from eqmq's own code: every class the package exports, its fields, properties
and methods with their signatures and docstrings, the slash commands DoCommand knows, and the constants.
Run it from the eqmq folder after changing the API (it imports eqmq, so protobuf must be installed):

    python tools/gen_reference.py

The docstrings are the documentation: keep them up to date, and this page follows."""
import dataclasses
import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import eqmq  # noqa: E402
from eqmq import bot as botmod  # noqa: E402

OUT = ROOT / "docs" / "reference.md"

# the order classes appear in, grouped as a reader looks for them
GROUPS = [
    ("The session", ["connect", "Bot", "CommandResult", "Refused", "MQPlugin", "load_plugins"]),
    ("Top-level objects (TLOs)", ["Me", "Spawn", "Group", "GroupMember", "Raid", "RaidMember", "Zone", "ZoneExit"]),
    ("What you carry and cast", ["Item", "Buff", "Gem", "BookSpell", "Resists", "BotGear", "PackItem"]),
    ("Results and events", ["MoveResult", "NavNote", "LootResult", "Merchant", "Parcel", "Consider", "Death",
                            "SkillUp", "ZoneChange", "Chat", "Message"]),
]


def first_para(doc):
    return (doc or "").strip().split("\n\n")[0].replace("\n", " ").strip()


def esc(s):
    return (s or "").replace("|", "\\|")


def auto_doc(cls, doc):
    """A dataclass's generated docstring (its signature) says nothing a fields table doesn't."""
    return doc and doc.startswith(cls.__name__ + "(")


def sig(obj, name):
    try:
        s = str(inspect.signature(obj))
    except (TypeError, ValueError):
        return name
    s = re.sub(r"\(self,?\s*", "(", s).replace("'", "")
    return f"{name}{s}"


def class_section(name, cls):
    md = [f"### {name}", ""]
    doc = inspect.getdoc(cls)
    if doc and not auto_doc(cls, doc):
        md += [doc, ""]
    if dataclasses.is_dataclass(cls):
        rows = [f"| `{f.name}` | `{esc(str(f.type).replace('typing.', ''))}` |" for f in dataclasses.fields(cls)
                if not f.name.startswith("_")]
        if rows:
            md += ["| Field | Type |", "|---|---|", *rows, ""]
    props, methods = [], []
    for n, member in inspect.getmembers(cls):
        if n.startswith("_"):
            continue
        raw = inspect.getattr_static(cls, n)
        if isinstance(raw, property):
            props.append((n, first_para(inspect.getdoc(raw))))
        elif inspect.isfunction(member) or inspect.iscoroutinefunction(member):
            if dataclasses.is_dataclass(cls) and n in ("__init__",):
                continue
            methods.append((n, member))
    if props:
        md += ["| Property | |", "|---|---|", *[f"| `{n}` | {esc(d)} |" for n, d in props], ""]
    if methods:
        md += ["| Method | |", "|---|---|"]
        for n, m in methods:
            kind = "async " if inspect.iscoroutinefunction(m) else ""
            md.append(f"| `{kind}{esc(sig(m, n))}` | {esc(first_para(inspect.getdoc(m)))} |")
        md.append("")
    return md


def slash_commands():
    src = inspect.getsource(botmod.Bot.DoCommand)
    words = set(re.findall(r'word == "(/[a-z]+)"', src))
    for group in re.findall(r"word in \(([^)]*)\)", src):
        words |= set(re.findall(r'"(/[a-z]+)"', group))
    words |= set(getattr(botmod, "_CHANNEL_COMMANDS", {}).keys())
    return sorted(words)


def main():
    exported = {n: getattr(eqmq, n) for n in dir(eqmq) if not n.startswith("_")}
    md = ["# eqmq reference",
          "",
          "Generated from the code by `tools/gen_reference.py`; don't edit by hand. The README is the tour; this is "
          "the list. Names follow MacroQuest where MacroQuest has one (`Me.PctHPs`, `Spawn.Distance`), and the "
          "server's protocol is in [headless-protocol.md](https://github.com/pjwendy/Server/blob/headless/docs/headless-protocol.md).",
          ""]
    toc = []
    for title, names in GROUPS:
        toc.append(f"- {title}: " + ", ".join(f"[{n}](#{n.lower()})" for n in names if n in exported))
    md += [*toc, "- [Slash commands](#slash-commands)", "- [Constants](#constants)", ""]
    done = set()
    for title, names in GROUPS:
        md += [f"## {title}", ""]
        for n in names:
            obj = exported.get(n)
            if obj is None:
                continue
            done.add(n)
            if inspect.isclass(obj):
                md += class_section(n, obj)
            else:
                kind = "async " if inspect.iscoroutinefunction(obj) else ""
                md += [f"### {n}", "", f"`{kind}{sig(obj, n)}`", "", inspect.getdoc(obj) or "", ""]
    others = [n for n, o in exported.items() if inspect.isclass(o) and n not in done and o.__module__.startswith("eqmq")
              and n not in ("INetworkClient", "ProtobufNetworkClient")]
    if others:
        md += ["## Other classes", ""]
        for n in sorted(others):
            md += class_section(n, exported[n])
    md += ["## Slash commands", "",
           "`await bot.DoCommand(line)` runs these, MacroQuest-style; a plugin adds its own with "
           "`bot.register_command(name, handler)`. GM commands are said: `/say #zone qeynos` (if the account's status "
           "allows them). EQEmu bot commands go through `/bot`: `/bot follow` is said as `^follow`.", "",
           ", ".join(f"`{w}`" for w in slash_commands()), ""]
    consts = [(n, o) for n, o in exported.items() if n.isupper() and isinstance(o, (int, str, float, tuple, list, dict, range))]
    md += ["## Constants", "", "| Name | Value |", "|---|---|"]
    for n, o in sorted(consts):
        v = repr(o)
        md.append(f"| `{n}` | `{esc(v if len(v) < 80 else v[:77] + '...')}` |")
    md.append("")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(md))
    print(f"{OUT.relative_to(ROOT)}: {len(done) + len(others)} classes and functions, {len(slash_commands())} slash commands")


if __name__ == "__main__":
    main()
