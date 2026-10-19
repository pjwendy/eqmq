"""eqmq: an MQ2-shaped SDK for EQEmu headless characters.

    bot = await eqmq.connect("127.0.0.1", 9100, token=TOKEN, character="Bifar")
    print(bot.Me.Name, bot.Me.PctHPs, bot.Zone.ShortName)
    print(bot.Spawn("npc radius 50"))
"""
from .bot import SDK_VERSION, Bot, CommandResult, Consider, Death, LootResult, Merchant, MoveResult, Refused, ZoneChange, connect
from .events import Chat, Message
from .network import INetworkClient, ProtobufNetworkClient
from .plugin import MQPlugin, load_plugins
from .proto.headless_pb2 import (CHAT_AUCTION, CHAT_GROUP, CHAT_GUILD, CHAT_OOC, CHAT_RAID, CHAT_SAY,
                                 CHAT_SHOUT, CHAT_TELL)
from .tlo import (BAG_SLOTS_BEGIN, BANK_BAGS_BEGIN, BANK_SLOTS, CURSOR_SLOT, GENERAL_SLOTS, WORN_SLOTS, Buff, BookSpell, Gem, Group,
                  GroupMember, Item, Me, Spawn, Zone, ZoneExit, BotGear)

__all__ = [
    "Bot", "Refused", "CommandResult", "MoveResult", "ZoneChange", "Consider", "LootResult", "Death",
    "Gem", "Buff", "BookSpell", "Item", "ZoneExit", "Merchant", "BotGear",
    "WORN_SLOTS", "GENERAL_SLOTS", "CURSOR_SLOT", "BAG_SLOTS_BEGIN", "BANK_SLOTS", "BANK_BAGS_BEGIN", "connect", "INetworkClient", "ProtobufNetworkClient",
    "Me", "Spawn", "Zone", "Group", "GroupMember", "Chat", "Message", "SDK_VERSION", "MQPlugin", "load_plugins",
    "CHAT_SAY", "CHAT_TELL", "CHAT_GROUP", "CHAT_GUILD", "CHAT_OOC", "CHAT_SHOUT", "CHAT_AUCTION", "CHAT_RAID",
]
