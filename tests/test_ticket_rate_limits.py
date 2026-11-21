"""Rate-limited channel edits must not monopolize ticket transactions."""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from src.commands.support import ticket as command
from src.utils import command_errors
from src.utils import ticket_service as service
from src.utils import tickets as store
from src.utils.db import PooledConnection
from test_ticket_role_sync import synchronization
from test_tickets import category_record, destination, install_session, ticket


@pytest.fixture(autouse=True)
def clear_cooldowns():
    service._channel_cooldowns.clear()
    yield
    service._channel_cooldowns.clear()


def test_channel_cooldowns_skip_repeated_requests_and_do_not_block_other_channels():
    async def scenario():
        env = destination()
        original = env.current.edit.side_effect
        env.current.edit.side_effect = discord.RateLimited(580.5)
        with pytest.raises(discord.RateLimited):
            await service.edit_channel(env.current, name="support")
        env.current.edit.side_effect = original
        with pytest.raises(discord.RateLimited) as caught:
            await service.edit_channel(env.current, name="support")
        assert caught.value.retry_after > 579
        env.current.edit.assert_awaited_once()
        await service.edit_channel(env.panel, name="other-ticket")
        assert env.panel.name == "other-ticket"
        service._channel_cooldowns[(1, 10)] = asyncio.get_running_loop().time() - 1
        await service.edit_channel(env.current, name="support")
        assert env.current.name == "support"
    asyncio.run(scenario())


def test_successful_rename_updates_the_original_object_and_avoids_duplicate_patches(monkeypatch):
    async def scenario():
        env = destination()
        updated = Mock(spec=discord.TextChannel)
        updated.name = "ticket-0001-🔴"
        env.current.edit = AsyncMock(return_value=updated)
        await service.edit_channel(env.current, name=updated.name)
        session = SimpleNamespace(set_channel_base_name=AsyncMock())
        await service.TicketService().sync_ticket_name(env.guild, env.current,
            ticket(channel_base_name="ticket-0001"), session, [])
        env.current.edit.assert_awaited_once()
    asyncio.run(scenario())


def test_category_sync_batches_name_permissions_and_topic_in_one_patch(monkeypatch):
    async def scenario():
        env, _role, _ticket, draft, _session, _message = synchronization(monkeypatch)
        await service.TicketService().save_category(env.interaction, draft, lambda: command.TicketPanel(None))
        env.current.edit.assert_awaited_once()
        assert {"name", "overwrites", "topic"}.issubset(env.current.edit.await_args.kwargs)
    asyncio.run(scenario())


def test_background_sync_commits_other_tickets_and_retries_after_channel_cooldown(monkeypatch):
    async def scenario():
        env = destination()
        first, second = ticket(), ticket(id=2, channel_id=20, channel_base_name="ticket-0002")
        session = SimpleNamespace(all=AsyncMock(return_value=[first, second]),
            get=AsyncMock(side_effect=lambda channel_id: first if channel_id == 10 else second),
            category=AsyncMock(return_value=category_record(staff_role_ids=(5,), version=2)), update_category=AsyncMock())
        install_session(monkeypatch, session)
        original = env.current.edit.side_effect
        env.current.edit.side_effect = discord.RateLimited(580)
        manager = service.TicketService()
        await manager.sync_categories(env.guild)
        assert [call.args[0].channel_id for call in session.update_category.await_args_list] == [20]
        await manager.sync_categories(env.guild)
        env.current.edit.assert_awaited_once()
        env.current.edit.side_effect = original
        service._channel_cooldowns[(1, 10)] = asyncio.get_running_loop().time() - 1
        await manager.sync_categories(env.guild)
        assert any(call.args[0].channel_id == 10 for call in session.update_category.await_args_list)
    asyncio.run(scenario())


def test_ready_reconnects_and_role_updates_share_one_worker_and_unload_cancels_it(monkeypatch):
    async def scenario():
        env = destination()
        monkeypatch.setattr(command, "GUILD_IDS", {1})
        entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def synchronize(guild):
            entered.set()
            await release.wait()

        manager = SimpleNamespace(sync_categories=AsyncMock(side_effect=synchronize),
            normalize_channel_names=AsyncMock(side_effect=lambda guild: finished.set()), refresh_panel_menus=AsyncMock())
        bot = SimpleNamespace(wait_until_ready=AsyncMock(), get_guild=lambda guild_id: env.guild)
        activity = command.TicketActivity(bot, manager)
        try:
            await activity.on_ready()
            worker = activity.retry_sync.get_task()
            await activity.on_ready()
            assert activity.retry_sync.get_task() is worker
            await asyncio.wait_for(entered.wait(), 1)
            await activity.synchronize()
            manager.sync_categories.assert_awaited_once()
            release.set()
            await asyncio.wait_for(finished.wait(), 1)
            await activity.synchronize()
            manager.refresh_panel_menus.assert_awaited_once()
        finally:
            await activity.cog_unload()
        assert worker.done()
    asyncio.run(scenario())


def test_background_sync_retries_after_contention_instead_of_giving_up(monkeypatch):
    async def scenario():
        env = destination()
        monkeypatch.setattr(command, "GUILD_IDS", {1})
        manager = SimpleNamespace(sync_categories=AsyncMock(side_effect=[store.TicketError("Busy"), None]),
            normalize_channel_names=AsyncMock(), refresh_panel_menus=AsyncMock())
        activity = command.TicketActivity(SimpleNamespace(get_guild=lambda guild_id: env.guild), manager)
        await activity.synchronize()
        assert not activity._panels_refreshed
        await activity.synchronize()
        assert activity._panels_refreshed == {1}
        manager.normalize_channel_names.assert_awaited_once()
    asyncio.run(scenario())


def test_global_rate_limit_errors_are_expected_and_do_not_emit_technical_alerts(monkeypatch):
    async def scenario():
        report = AsyncMock()
        monkeypatch.setattr(command_errors, "report_error", report)
        interaction = SimpleNamespace(extras={}, response=SimpleNamespace(is_done=lambda: False, send_message=AsyncMock()))
        await command_errors.handle_app_command_error(None, interaction, discord.RateLimited(580.5))
        report.assert_not_awaited()
        assert "581 secondes" in interaction.response.send_message.await_args.args[0]
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["timeout", "cancellation", "upstream_timeout"])
def test_mysql_timeout_and_cancellation_release_pooled_locks_and_roll_back(monkeypatch, failure):
    import aiomysql
    from src.core.db_init import init_db

    port = os.getenv("TICKET_TEST_DB_PORT")
    if not port:
        pytest.skip("Requires a disposable MySQL test database")

    async def scenario():
        pool = await aiomysql.create_pool(host="127.0.0.1", port=int(port), user="root", password="",
            db="reminder_test", charset="utf8mb4", autocommit=True, minsize=1, maxsize=2)

        async def connection():
            return PooledConnection(pool, await pool.acquire())

        monkeypatch.setattr(store, "get_db_connection", connection)
        try:
            db = await connection()
            try:
                await init_db(db)
            finally:
                db.close()
            entered = asyncio.Event()

            async def operation():
                async with store.ticket_session(424242) as session:
                    await session.execute("INSERT INTO admin_audit (guild_id, actor_id, action) VALUES (%s, %s, %s)",
                                          (424242, 1, "ticket.timeout-test"))
                    entered.set()
                    if failure == "upstream_timeout":
                        raise TimeoutError("Upstream timeout")
                    await asyncio.Event().wait()

            if failure == "timeout":
                monkeypatch.setattr(store, "TICKET_SESSION_TIMEOUT", 0.1)
                with pytest.raises(store.TicketError, match="interrompue"):
                    await asyncio.wait_for(operation(), 2)
            elif failure == "cancellation":
                task = asyncio.create_task(operation())
                await asyncio.wait_for(entered.wait(), 1)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                with pytest.raises(TimeoutError, match="Upstream timeout"):
                    await operation()
            async with store.ticket_session(424242) as session:
                assert await session.rows("SELECT id FROM admin_audit WHERE guild_id = %s AND action = %s",
                                          (424242, "ticket.timeout-test")) == ()
            db = await connection()
            try:
                async with db.cursor() as cursor:
                    await cursor.execute("SELECT IS_USED_LOCK(%s)", ("aurum:tickets:424242",))
                    assert (await cursor.fetchone())[0] is None
            finally:
                db.close()
        finally:
            pool.close()
            await pool.wait_closed()
    asyncio.run(scenario())
