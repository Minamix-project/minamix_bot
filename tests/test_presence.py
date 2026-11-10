"""Presence rotation order, reconnect behavior and worker cleanup."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from src.events import presence


def test_presence_rotates_the_requested_activities_and_uses_the_running_version_and_bot_name(monkeypatch):
    async def scenario():
        monkeypatch.setenv("BOT_VERSION", "v1.10.0")
        bot = SimpleNamespace(user=SimpleNamespace(name="Aurum"), is_ready=lambda: True, change_presence=AsyncMock())
        cog = presence.RotatingPresence(bot)
        for _ in range(5):
            await cog.rotate.coro(cog)
        activities = [call.kwargs["activity"] for call in bot.change_presence.await_args_list]
        assert [activity.type for activity in activities] == [
            discord.ActivityType.watching,
            discord.ActivityType.listening,
            discord.ActivityType.playing,
            discord.ActivityType.competing,
            discord.ActivityType.watching,
        ]
        assert [activity.name for activity in activities[:4]] == [
            "Les bots prendre le pouvoir",
            "Les plaintes des utilisateurs",
            "La version v1.10.0 de Aurum",
            "La lutte pour l'égalité entre bots et humains",
        ]
        monkeypatch.delenv("BOT_VERSION")
        bot.user.name = "Nouveau nom"
        cog.index = 2
        await cog.rotate.coro(cog)
        assert bot.change_presence.await_args.kwargs["activity"].name == "La version de développement de Nouveau nom"

    asyncio.run(scenario())


def test_repeated_ready_events_do_not_duplicate_the_worker_and_unload_cancels_it():
    async def scenario():
        bot = SimpleNamespace(user=SimpleNamespace(name="Aurum"), is_ready=lambda: True, change_presence=AsyncMock())
        cog = presence.RotatingPresence(bot)
        await cog.on_ready()
        task = cog.rotate.get_task()
        await cog.on_ready()
        assert cog.rotate.get_task() is task
        assert cog.rotate.minutes == 5
        await asyncio.sleep(0)
        await cog.cog_unload()
        assert task.done() and not cog.rotate.is_running()

    asyncio.run(scenario())


def test_presence_skips_disconnected_updates_and_retries_the_same_activity_after_a_failure():
    async def scenario():
        bot = SimpleNamespace(user=SimpleNamespace(name="Aurum"), is_ready=lambda: False, change_presence=AsyncMock())
        cog = presence.RotatingPresence(bot)
        await cog.rotate.coro(cog)
        bot.change_presence.assert_not_awaited()
        bot.is_ready = lambda: True
        bot.change_presence.side_effect = [OSError("Disconnected"), None]
        await cog.rotate.coro(cog)
        assert cog.index == 0
        await cog.rotate.coro(cog)
        assert cog.index == 1
        assert all(
            call.kwargs["activity"].type == discord.ActivityType.watching
            for call in bot.change_presence.await_args_list
        )

    asyncio.run(scenario())
