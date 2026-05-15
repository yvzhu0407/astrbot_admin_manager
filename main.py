import asyncio
import json
import os
import time
from sys import maxsize
from typing import Any

from astrbot.api import AstrBotConfig, star
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path


DEFAULT_DATA = {
    "owners": [],
    "blocked": {},
    "usage": {},
    "errors": {},
}


@filter.command_group("apm")
def apm():
    pass


class Main(star.Star):
    def __init__(self, context: star.Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context, config)
        self.context = context
        self.config = config or {}
        self.plugin_name = "astrbot_admin_manager"
        self._lock = asyncio.Lock()
        self._data_path = os.path.join(
            get_astrbot_plugin_data_path(),
            self.plugin_name,
            "data.json",
        )
        self._data = self._load_data()

    def _load_data(self) -> dict[str, Any]:
        if not os.path.exists(self._data_path):
            return json.loads(json.dumps(DEFAULT_DATA))
        try:
            with open(self._data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return json.loads(json.dumps(DEFAULT_DATA))
        for key, value in DEFAULT_DATA.items():
            data.setdefault(key, json.loads(json.dumps(value)))
        return data

    def _save_data_unlocked(self) -> None:
        os.makedirs(os.path.dirname(self._data_path), exist_ok=True)
        with open(self._data_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    async def _save_data(self) -> None:
        async with self._lock:
            self._save_data_unlocked()

    def _configured_owners(self) -> set[str]:
        return {str(owner) for owner in self.config.get("owner_ids", []) if str(owner)}

    def _owners(self) -> set[str]:
        return self._configured_owners() | {
            str(owner) for owner in self._data.get("owners", []) if str(owner)
        }

    def _is_owner(self, event: AstrMessageEvent) -> bool:
        return event.get_sender_id() in self._owners()

    def _star_name_by_module_path(self, module_path: str) -> str | None:
        for plugin in self.context.get_all_stars():
            if plugin.module_path == module_path:
                return plugin.name
        return None

    def _registered_plugin_names(self) -> set[str]:
        return {plugin.name for plugin in self.context.get_all_stars() if plugin.name}

    def _blocked_plugins_for_user(self, user_id: str) -> set[str]:
        return set(self._data.get("blocked", {}).get(user_id, []))

    def _format_time(self, timestamp: float | int | None) -> str:
        if not timestamp:
            return "无"
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(timestamp)))

    async def _reply(self, event: AstrMessageEvent, text: str) -> None:
        await event.send(MessageChain().message(text))

    async def _require_owner(self, event: AstrMessageEvent) -> bool:
        if self._is_owner(event):
            return True
        if not self._owners():
            await self._reply(
                event,
                "尚未配置主人。请先在插件配置 owner_ids 中填写主人 QQ 号。",
            )
        else:
            await self._reply(event, "只有主人可以使用这个命令。")
        return False

    def _record_usage_unlocked(self, plugin_names: set[str], user_id: str) -> None:
        now = int(time.time())
        usage = self._data.setdefault("usage", {})
        for plugin_name in sorted(plugin_names):
            plugin_stats = usage.setdefault(
                plugin_name,
                {"total": 0, "last_used": 0, "users": {}},
            )
            plugin_stats["total"] = int(plugin_stats.get("total", 0)) + 1
            plugin_stats["last_used"] = now
            user_stats = plugin_stats.setdefault("users", {}).setdefault(
                user_id,
                {"count": 0, "last_used": 0},
            )
            user_stats["count"] = int(user_stats.get("count", 0)) + 1
            user_stats["last_used"] = now

    def _record_error_unlocked(
        self,
        plugin_name: str,
        handler_name: str,
        error: BaseException,
        traceback_text: str,
    ) -> None:
        now = int(time.time())
        errors = self._data.setdefault("errors", {})
        plugin_errors = errors.setdefault(
            plugin_name,
            {"total": 0, "last_error": 0, "handlers": {}, "last_message": ""},
        )
        plugin_errors["total"] = int(plugin_errors.get("total", 0)) + 1
        plugin_errors["last_error"] = now
        plugin_errors["last_message"] = str(error)
        plugin_errors["last_traceback"] = traceback_text[-4000:]
        handler_errors = plugin_errors.setdefault("handlers", {}).setdefault(
            handler_name,
            {"count": 0, "last_error": 0, "last_message": ""},
        )
        handler_errors["count"] = int(handler_errors.get("count", 0)) + 1
        handler_errors["last_error"] = now
        handler_errors["last_message"] = str(error)

    @filter.event_message_type(filter.EventMessageType.ALL, priority=maxsize - 10)
    async def enforce_user_plugin_acl(self, event: AstrMessageEvent) -> None:
        handlers = event.get_extra("activated_handlers", [])
        if not handlers:
            return

        user_id = event.get_sender_id()
        if not user_id:
            return

        blocked_plugins = self._blocked_plugins_for_user(user_id)
        allowed_plugins: set[str] = set()
        denied_plugins: set[str] = set()
        kept_handlers = []

        for handler in handlers:
            plugin_name = self._star_name_by_module_path(handler.handler_module_path)
            if not plugin_name or plugin_name == self.plugin_name:
                kept_handlers.append(handler)
                continue
            if plugin_name in blocked_plugins:
                denied_plugins.add(plugin_name)
                continue
            allowed_plugins.add(plugin_name)
            kept_handlers.append(handler)

        if len(kept_handlers) != len(handlers):
            handlers[:] = kept_handlers

        if allowed_plugins:
            async with self._lock:
                self._record_usage_unlocked(allowed_plugins, user_id)
                self._save_data_unlocked()

        if denied_plugins and not allowed_plugins:
            plugin_text = "、".join(sorted(denied_plugins))
            reply = str(self.config.get("block_reply", "你不能使用插件 {plugin}。"))
            await self._reply(event, reply.replace("{plugin}", plugin_text))
            event.stop_event()

    @filter.on_plugin_error()
    async def on_plugin_error(
        self,
        event: AstrMessageEvent,
        plugin_name: str,
        handler_name: str,
        error: BaseException,
        traceback_text: str,
    ) -> None:
        async with self._lock:
            self._record_error_unlocked(plugin_name, handler_name, error, traceback_text)
            self._save_data_unlocked()

    @apm.command("help")
    async def help(self, event: AstrMessageEvent) -> None:
        if not await self._require_owner(event):
            return
        await self._reply(
            event,
            "可用命令：\n"
            "/apm plugins\n"
            "/apm on <插件名>\n"
            "/apm off <插件名>\n"
            "/apm block <用户ID> <插件名>\n"
            "/apm unblock <用户ID> <插件名>\n"
            "/apm blocks\n"
            "/apm stats [插件名]\n"
            "/apm errors [插件名]\n"
            "/apm owner add <用户ID>\n"
            "/apm owner remove <用户ID>\n"
            "/apm owner list\n"
            "/apm claim",
        )

    @apm.command("plugins")
    async def plugins(self, event: AstrMessageEvent) -> None:
        if not await self._require_owner(event):
            return
        lines = []
        for plugin in sorted(self.context.get_all_stars(), key=lambda item: item.name or ""):
            name = plugin.name or "未命名"
            state = "启用" if plugin.activated else "停用"
            lines.append(f"{name}: {state}")
        await self._reply(event, "\n".join(lines) if lines else "没有已加载插件。")

    @apm.command("on")
    async def turn_on(self, event: AstrMessageEvent, plugin_name: str) -> None:
        if not await self._require_owner(event):
            return
        manager = getattr(self.context, "_star_manager", None)
        if manager is None:
            await self._reply(event, "当前 AstrBot 版本未暴露插件管理器，无法启用插件。")
            return
        await manager.turn_on_plugin(plugin_name)
        await self._reply(event, f"已启用插件：{plugin_name}")

    @apm.command("off")
    async def turn_off(self, event: AstrMessageEvent, plugin_name: str) -> None:
        if not await self._require_owner(event):
            return
        if plugin_name == self.plugin_name:
            await self._reply(event, "不能通过本插件停用自身。")
            return
        manager = getattr(self.context, "_star_manager", None)
        if manager is None:
            await self._reply(event, "当前 AstrBot 版本未暴露插件管理器，无法停用插件。")
            return
        await manager.turn_off_plugin(plugin_name)
        await self._reply(event, f"已停用插件：{plugin_name}")

    @apm.command("block")
    async def block_user(self, event: AstrMessageEvent, user_id: str, plugin_name: str) -> None:
        if not await self._require_owner(event):
            return
        if plugin_name == self.plugin_name:
            await self._reply(event, "不能禁止用户使用本插件。")
            return
        if plugin_name not in self._registered_plugin_names():
            await self._reply(event, f"插件不存在或未加载：{plugin_name}")
            return
        async with self._lock:
            blocked = self._data.setdefault("blocked", {}).setdefault(user_id, [])
            if plugin_name not in blocked:
                blocked.append(plugin_name)
                blocked.sort()
            self._save_data_unlocked()
        await self._reply(event, f"已禁止用户 {user_id} 使用插件 {plugin_name}。")

    @apm.command("unblock")
    async def unblock_user(
        self,
        event: AstrMessageEvent,
        user_id: str,
        plugin_name: str,
    ) -> None:
        if not await self._require_owner(event):
            return
        async with self._lock:
            blocked = self._data.setdefault("blocked", {}).get(user_id, [])
            if plugin_name in blocked:
                blocked.remove(plugin_name)
            if not blocked:
                self._data.setdefault("blocked", {}).pop(user_id, None)
            self._save_data_unlocked()
        await self._reply(event, f"已允许用户 {user_id} 使用插件 {plugin_name}。")

    @apm.command("blocks")
    async def blocks(self, event: AstrMessageEvent) -> None:
        if not await self._require_owner(event):
            return
        blocked = self._data.get("blocked", {})
        if not blocked:
            await self._reply(event, "当前没有用户级插件黑名单。")
            return
        lines = [f"{user_id}: {'、'.join(plugin_names)}" for user_id, plugin_names in sorted(blocked.items())]
        await self._reply(event, "\n".join(lines))

    @apm.command("stats")
    async def stats(self, event: AstrMessageEvent, plugin_name: str = "") -> None:
        if not await self._require_owner(event):
            return
        usage = self._data.get("usage", {})
        names = [plugin_name] if plugin_name else sorted(usage)
        lines = []
        for name in names:
            item = usage.get(name)
            if not item:
                continue
            lines.append(
                f"{name}: {item.get('total', 0)} 次，最后使用 {self._format_time(item.get('last_used'))}"
            )
        await self._reply(event, "\n".join(lines) if lines else "暂无使用统计。")

    @apm.command("errors")
    async def errors(self, event: AstrMessageEvent, plugin_name: str = "") -> None:
        if not await self._require_owner(event):
            return
        errors = self._data.get("errors", {})
        names = [plugin_name] if plugin_name else sorted(errors)
        lines = []
        for name in names:
            item = errors.get(name)
            if not item:
                continue
            lines.append(
                f"{name}: {item.get('total', 0)} 次，最后错误 {self._format_time(item.get('last_error'))}，{item.get('last_message', '')}"
            )
        await self._reply(event, "\n".join(lines) if lines else "暂无错误统计。")

    @apm.command("claim")
    async def claim(self, event: AstrMessageEvent) -> None:
        if self._owners():
            await self._reply(event, "已存在主人，不能认领。")
            return
        if not bool(self.config.get("allow_first_owner_claim", False)):
            await self._reply(event, "未开启首次主人认领。请先在插件配置 owner_ids 中填写主人 QQ 号。")
            return
        user_id = event.get_sender_id()
        async with self._lock:
            owners = self._data.setdefault("owners", [])
            if user_id not in owners:
                owners.append(user_id)
            self._save_data_unlocked()
        await self._reply(event, f"已设置主人：{user_id}")

    @apm.group("owner")
    def owner():
        pass

    @owner.command("add")
    async def owner_add(self, event: AstrMessageEvent, user_id: str) -> None:
        if not await self._require_owner(event):
            return
        async with self._lock:
            owners = self._data.setdefault("owners", [])
            if user_id not in owners:
                owners.append(user_id)
                owners.sort()
            self._save_data_unlocked()
        await self._reply(event, f"已添加主人：{user_id}")

    @owner.command("remove")
    async def owner_remove(self, event: AstrMessageEvent, user_id: str) -> None:
        if not await self._require_owner(event):
            return
        configured = self._configured_owners()
        if user_id in configured:
            await self._reply(event, "该主人来自插件配置，请在 WebUI 配置中移除。")
            return
        async with self._lock:
            owners = self._data.setdefault("owners", [])
            if user_id in owners:
                owners.remove(user_id)
            self._save_data_unlocked()
        await self._reply(event, f"已移除主人：{user_id}")

    @owner.command("list")
    async def owner_list(self, event: AstrMessageEvent) -> None:
        if not await self._require_owner(event):
            return
        owners = sorted(self._owners())
        await self._reply(event, "主人列表：" + ("、".join(owners) if owners else "无"))
