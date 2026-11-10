"""Ticket journals share moderation formatting and keep transcript content private."""

import asyncio

import discord
import pytest

from src.utils.ticket_logs import build_ticket_log
from src.utils.ticket_service import TicketService
from test_tickets import destination, ticket


@pytest.mark.parametrize(
    "action,detail,target_field",
    [
        ("created", None, None),
        ("closed", "Private closure reason", None),
        ("reopened", None, None),
        ("added", "4", "Membre concerné"),
        ("removed", "4", "Membre concerné"),
        ("linked", "4", "Utilisateur concerné"),
        ("renamed", "support-rp", "Nouveau nom"),
    ],
)
def test_ticket_log_uses_named_fields_timestamp_bot_footer_and_creator_avatar(action, detail, target_field):
    env = destination()
    embed = build_ticket_log(env.guild, ticket(), action, env.staff.id, detail=detail)
    fields = {field.name: field.value for field in embed.fields}
    assert fields["Salon"] == "<#10> (`10`)"
    assert fields["Ticket"] == "#0001"
    assert fields["Catégorie"] == "Signalement"
    assert "<@2> (`2`)" in fields["Créateur"]
    assert "<@3> (`3`)" in fields["Par"]
    assert embed.timestamp is not None
    assert embed.footer.text == "Aurum"
    assert embed.footer.icon_url == "https://example.test/avatar.png"
    assert embed.thumbnail.url == "https://example.test/avatar-2.png"
    assert embed.description is None
    assert "Private closure reason" not in str(embed.to_dict())
    if target_field:
        assert target_field in fields
        assert "<@4>" in fields[target_field] if action != "renamed" else fields[target_field] == "support-rp"
    assert len(embed) <= 6000


def test_transcript_notification_uses_same_layout_and_respects_long_reason_limits():
    async def scenario():
        env = destination()
        reason = "*" * 1000
        closed = ticket(transcript_channel_id=20, closed_by=3, close_reason=reason)
        assert await TicketService().send_transcript(env.guild, closed, reason.encode()) is None
        sent = env.panel.send.await_args.kwargs
        embed = sent["embed"]
        fields = {field.name: field.value for field in embed.fields}
        assert embed.title == "🔒 Ticket fermé"
        assert embed.colour == discord.Color.red()
        assert embed.footer.text == "Aurum" and embed.timestamp
        assert len(fields["Raison"]) <= 1024
        assert "transcript joint" in fields["Raison"]
        assert sent["file"].fp.read().decode() == reason
        assert sent["allowed_mentions"].to_dict()["parse"] == []

    asyncio.run(scenario())
