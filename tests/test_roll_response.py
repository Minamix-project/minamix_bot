import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
from discord.ext import commands
import pytest

from src.commands.rp import roll as command
from src.utils import dice


def interaction():
    return SimpleNamespace(
        user=SimpleNamespace(display_name="Alice", display_avatar=SimpleNamespace(url="https://example.com/alice.png")),
        client=SimpleNamespace(user=SimpleNamespace(name="MinamixBot", avatar=None)),
        response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )


def registered_command():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    asyncio.run(command.register(bot))
    return bot.tree.get_command("roll")


def test_small_output_is_kept_without_attachment():
    output = "🎲 2d6 `[4 4]` → **8**"
    assert command.prepare_output(output) == (output, None)


@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("suffix,total", [("", 4000), (" k1", 20)])
def test_large_series_delivers_totals_and_exact_file_without_rerolling(monkeypatch, private, suffix, total):
    draw = Mock(return_value=20)
    monkeypatch.setattr(dice, "_d", draw)
    current = interaction()
    captured = []

    async def capture(**kwargs):
        captured.append((kwargs, kwargs["file"].fp.read().decode("utf-8")))

    current.followup.send.side_effect = capture
    expression = ("p " if private else "") + "20 200d20" + suffix
    asyncio.run(registered_command().callback(current, expression))
    assert draw.call_count == 4000
    assert current.response.defer.await_args.kwargs == {"ephemeral": private, "thinking": True}
    current.response.send_message.assert_not_awaited()
    kwargs, transcript = captured[0]
    embed = kwargs["embed"]
    assert len(embed.description) <= 4096
    assert len(embed) <= 6000
    assert embed.description.count(f"**{total}**") == 20
    assert transcript.count(f"**{total}**") == 20
    assert transcript.count("20 ") > 3000
    assert kwargs["ephemeral"] is private
    assert kwargs["allowed_mentions"].to_dict() == {"parse": []}
    assert kwargs["file"].fp.closed


def test_normal_roll_stays_one_short_response(monkeypatch):
    monkeypatch.setattr(dice, "_d", lambda _sides: 20)
    current = interaction()
    asyncio.run(registered_command().callback(current, "200d20"))
    current.response.defer.assert_not_awaited()
    current.followup.send.assert_not_awaited()
    kwargs = current.response.send_message.await_args.kwargs
    assert kwargs["embed"].description.endswith("**4000**")
    assert "file" not in kwargs


@pytest.mark.parametrize("expression", ["1d1 blabla", "1d1/0", "1d1 ir1", "1d1 ie1"])
def test_invalid_rolls_have_clear_private_feedback(monkeypatch, expression):
    draw = Mock()
    monkeypatch.setattr(dice, "_d", draw)
    current = interaction()
    asyncio.run(registered_command().callback(current, expression))
    kwargs = current.response.send_message.await_args.kwargs
    assert "❌" in kwargs["embed"].description
    assert kwargs["ephemeral"]
    current.followup.send.assert_not_awaited()
    draw.assert_not_called()


def test_chain_limit_failure_is_private_and_does_not_deliver_partial_results(monkeypatch):
    monkeypatch.setattr(dice, "EXPLODE_CAP", 2)
    monkeypatch.setattr(dice, "_d", lambda _sides: 6)
    current = interaction()
    asyncio.run(registered_command().callback(current, "1d6 ie6"))
    assert "Jet annulé" in current.response.send_message.await_args.args[0]
    assert current.response.send_message.await_args.kwargs["ephemeral"]
    current.followup.send.assert_not_awaited()


def test_help_fits_a_single_embed_description():
    assert len(dice.get_help().encode("utf-16-le")) // 2 <= 4096


def test_budget_exhaustion_is_a_private_explanation(monkeypatch):
    current = interaction()
    monkeypatch.setattr(dice, "_d", lambda _sides: 2)
    asyncio.run(registered_command().callback(current, "200d2 ie2"))
    assert "tirages par commande" in current.response.send_message.await_args.args[0]
    assert current.response.send_message.await_args.kwargs["ephemeral"]
    current.followup.send.assert_not_awaited()


def test_long_unicode_output_is_bounded_and_complete_in_file():
    output = "😀é🎲" * 4000
    description, file = command.prepare_output(output)
    try:
        assert len(description) <= 4096
        assert len(description.encode("utf-16-le")) // 2 <= 4096
        assert "fichier joint" in description
        assert file.fp.read().decode("utf-8") == output
    finally:
        file.close()
        file.fp.close()


def test_attachment_is_closed_when_discord_delivery_fails(monkeypatch):
    file = discord.File(BytesIO(b"complete"), filename="resultats-des.txt")
    monkeypatch.setattr(command, "prepare_output", lambda _output: ("Résumé", file))
    monkeypatch.setattr(command, "dice_roll", lambda _expression: ("output", False))
    current = interaction()
    current.followup.send.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions")
    with pytest.raises(discord.Forbidden):
        asyncio.run(registered_command().callback(current, "1d6"))
    assert file.fp.closed
