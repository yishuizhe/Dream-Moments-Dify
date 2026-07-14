"""Discover and run external Dream plugins without coupling them to the core."""

from __future__ import annotations

import importlib.util
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any


@dataclass(slots=True)
class LoadedPlugin:
    name: str
    instance: Any
    module: ModuleType
    directory: Path


class PluginManager:
    """Load ``plugins/*/dream_plugin.py`` and safely dispatch group messages."""

    def __init__(
        self,
        plugins_dir: str | Path,
        logger: logging.Logger | None = None,
        *,
        auto_load: bool = True,
    ) -> None:
        self.plugins_dir = Path(plugins_dir).expanduser().resolve()
        self.logger = logger or logging.getLogger(__name__)
        self.plugins: list[LoadedPlugin] = []
        if auto_load:
            self.load_plugins()

    def load_plugins(self) -> list[LoadedPlugin]:
        self.plugins = []
        if not self.plugins_dir.is_dir():
            return self.plugins

        for entry in sorted(self.plugins_dir.iterdir(), key=lambda item: item.name.lower()):
            plugin_file = entry / "dream_plugin.py"
            if not entry.is_dir() or entry.name.startswith(".") or not plugin_file.is_file():
                continue
            try:
                loaded = self._load_plugin(entry, plugin_file)
            except Exception as exc:
                self.logger.error(
                    "External plugin %s failed to load (%s)",
                    entry.name,
                    type(exc).__name__,
                )
                continue
            self.plugins.append(loaded)
            self.logger.info("External plugin loaded: %s", loaded.name)
        return list(self.plugins)

    def _load_plugin(self, plugin_dir: Path, plugin_file: Path) -> LoadedPlugin:
        module_name = f"dream_external_{plugin_dir.name}_{abs(hash(plugin_file))}"
        spec = importlib.util.spec_from_file_location(module_name, plugin_file)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create module spec for {plugin_file}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        sys.path.insert(0, str(plugin_dir))
        try:
            spec.loader.exec_module(module)
            factory = getattr(module, "create_plugin", None)
            if not callable(factory):
                raise AttributeError("create_plugin is missing")
            instance = factory(plugin_dir=str(plugin_dir), logger=self.logger)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        finally:
            try:
                sys.path.remove(str(plugin_dir))
            except ValueError:
                pass

        name = str(getattr(instance, "name", plugin_dir.name) or plugin_dir.name)
        return LoadedPlugin(name=name, instance=instance, module=module, directory=plugin_dir)

    def configure_services(self, **services: Any) -> None:
        """Inject optional core services into plugins that explicitly accept them."""
        for loaded in self.plugins:
            configure = getattr(loaded.instance, "configure_services", None)
            if not callable(configure):
                continue
            try:
                configure(**services)
            except Exception as exc:
                self.logger.error(
                    "External plugin %s service configuration failed (%s)",
                    loaded.name,
                    type(exc).__name__,
                )

    def handle_group_message(
        self,
        *,
        chat_id: str,
        sender_id: str,
        sender_name: str,
        content: str,
        bot_name: str = "",
        timestamp: datetime | None = None,
        is_self: bool = False,
    ) -> str | None:
        message = {
            "chat_id": chat_id,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "content": content,
            "bot_name": bot_name,
            "timestamp": timestamp if isinstance(timestamp, datetime) else datetime.now(),
            "is_group": True,
            "is_self": bool(is_self),
        }
        first_reply: str | None = None
        for loaded in self.plugins:
            try:
                reply = loaded.instance.handle_message(message)
            except Exception as exc:
                self.logger.error(
                    "External plugin %s failed while handling a message (%s)",
                    loaded.name,
                    type(exc).__name__,
                )
                continue
            if first_reply is None and isinstance(reply, str) and reply.strip():
                first_reply = reply.strip()
        return first_reply
