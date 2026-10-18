"""eqmq: an MQ2-shaped SDK for EQEmu headless characters.

    bot = await eqmq.connect("127.0.0.1", 9100, token=TOKEN, character="Bifar")
    print(bot.Me.Name, bot.Me.PctHPs, bot.Zone.ShortName)
    print(bot.Spawn("npc radius 50"))
"""
from .bot import SDK_VERSION, Bot, Refused, connect
from .network import INetworkClient, ProtobufNetworkClient
from .tlo import Me, Spawn, Zone

__all__ = ["Bot", "Refused", "connect", "INetworkClient", "ProtobufNetworkClient", "Me", "Spawn", "Zone", "SDK_VERSION"]
