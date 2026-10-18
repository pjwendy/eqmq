"""MQ2-style plugins.

A plugin subclasses MQPlugin and overrides any of on_load (once, after login), on_frame
(every frame, 100ms by default) and on_clean (once, when the bot stops). Plugins can add
slash commands (bot.register_command) and TLOs (bot.register_tlo).

Plugins run in-process: isolation is a convention, not a security boundary. They only ever
see protocol state, never raw packets.
"""
from __future__ import annotations

import importlib.util
import inspect
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .bot import Bot

log = logging.getLogger("eqmq.plugin")


class MQPlugin:
    def __init__(self, bot: "Bot"):
        self.bot = bot

    @property
    def name(self) -> str:
        return type(self).__name__

    async def on_load(self) -> None:
        """Called once before the first frame."""

    async def on_frame(self) -> None:
        """Called every frame while connected. Keep it quick; start tasks for long work."""

    async def on_clean(self) -> None:
        """Called once when the bot stops running."""


def load_plugins(directory: str, bot: "Bot") -> list[MQPlugin]:
    """Instantiate every MQPlugin subclass found in directory/*.py (files starting with _ are skipped)."""
    plugins: list[MQPlugin] = []
    if not os.path.isdir(directory):
        raise FileNotFoundError(f"plugin directory {directory!r} not found")

    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue
        path = os.path.join(directory, filename)
        module_name = f"eqmq_plugin_{filename[:-3]}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception:
            log.exception("failed to import plugin file %s", path)
            continue
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, MQPlugin) and cls is not MQPlugin and cls.__module__ == module_name:
                plugins.append(cls(bot))
                log.info("loaded plugin %s from %s", cls.__name__, filename)
    return plugins
