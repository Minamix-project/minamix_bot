"""Discord command and component tests with real views and a mocked transport."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
from discord.ext import commands
import pytest

from src.commands.rp import rproles
from src.utils import rp_roles as store
from src.utils import rp_role_ui
from src.utils.rp_role_profiles import profile_fields

GUILD = 301
CACTUS = 81
MEMBER = 41
CHARACTERS = (
    store.Character(1, "Néréide", "n:", "https://example.org/avatar.png"),
    store.Character(2, "Orion", "o:", "https://example.org/orion.png"),
)
CATEGORY = store.Category(100, "Pays", 10, "multiple")


def role_payload(role_id, name, permission=0, color=0):
    return {
        "id": str(role_id), "name": name, "permissions": str(permission),
        "colors": {"primary_color": color}, "position": 1,
    }


def member(guild, user_id, roles=()):
    data = {
        "user": {"id": str(user_id), "username": f"membre-{user_id}", "discriminator": "0", "avatar": None},
        "roles": [str(role_id) for role_id in roles],
        "flags": 0,
    }
    return discord.Member(data=data, guild=guild, state=guild._state)


class Transport:
    def __init__(self, bot, guild, actor):
        self.bot = bot
        self.guild = guild
        self.actor = actor
        self.view = None
        self.message = SimpleNamespace(edit=AsyncMock())
        self.embed = None

    def interaction(self, *, actor=None, guild=None):
        guild = guild or self.guild
        response = SimpleNamespace(
            defer=AsyncMock(), send_message=AsyncMock(), send_modal=AsyncMock(),
        )
        response.is_done = lambda: bool(response.defer.await_count)

        async def edit(**kwargs):
            self.view = kwargs["view"]
            self.embed = kwargs["embed"]
            return self.message

        return SimpleNamespace(
            client=self.bot, user=actor or self.actor, guild=guild, guild_id=guild.id, response=response,
            edit_original_response=AsyncMock(side_effect=edit), followup=SimpleNamespace(send=AsyncMock()),
        )

    async def command(self, name):
        inter = self.interaction()
        await self.bot.tree.get_command(name).callback(inter)
        inter.response.defer.assert_awaited_once_with(ephemeral=True)
        assert inter.edit_original_response.await_args.kwargs["allowed_mentions"].to_dict() == {"parse": []}
        return inter

    async def press(self, label, *, view=None, actor=None):
        view = view or self.view
        button = next(item for item in view.children if isinstance(item, discord.ui.Button) and item.label == label)
        inter = self.interaction(actor=actor)
        if await view.interaction_check(inter):
            await button.callback(inter)
        return inter

    async def select(self, kind, values, *, row=0):
        view = self.view
        select = next(item for item in view.children if isinstance(item, kind) and item.row == row)
        select._values = values
        inter = self.interaction()
        assert await view.interaction_check(inter)
        await select.callback(inter)
        return inter


@asynccontextmanager
async def setup(monkeypatch, actor_role):
    monkeypatch.setattr(rp_role_ui, "GUILD_IDS", {GUILD})
    async with commands.Bot(command_prefix="!", intents=discord.Intents.default()) as bot:
        bot._connection.user = discord.ClientUser(state=bot._connection, data={
            "id": "99", "username": "MinamixBot", "discriminator": "0", "avatar": None,
        })
        guild = discord.Guild(state=bot._connection, data={
            "id": str(GUILD), "name": "Aurum", "owner_id": "9999",
            "roles": [
                role_payload(GUILD, "@everyone"),
                role_payload(71, "Admin", discord.Permissions(administrator=True).value),
                role_payload(72, "Gestion", discord.Permissions(manage_guild=True).value),
                role_payload(CACTUS, "Cactus"),
                role_payload(51, "Lyndera", color=0x9488AA),
                role_payload(52, "Silfus"),
            ],
        })
        player = member(guild, MEMBER)
        actor = member(guild, 42, [actor_role] if actor_role else [])
        guild._add_member(player)
        guild._add_member(actor)
        await rproles.register(bot)

        async def unexpected(*args, **kwargs):
            pytest.fail("RP references must never mutate live Discord roles.")

        for model, methods in (
            (discord.Member, ("add_roles", "remove_roles")),
            (discord.Role, ("edit", "delete")),
            (discord.Guild, ("create_role",)),
        ):
            for method in methods:
                monkeypatch.setattr(model, method, unexpected)
        monkeypatch.setattr(discord.Guild, "fetch_member", AsyncMock(return_value=actor))
        monkeypatch.setattr(discord.Guild, "fetch_roles", AsyncMock(return_value=guild.roles))
        monkeypatch.setattr(store, "validator_roles", AsyncMock(return_value=frozenset({CACTUS})))
        monkeypatch.setattr(store, "settings", AsyncMock(return_value=store.Settings(3, False)))
        monkeypatch.setattr(store, "list_characters", AsyncMock(return_value=CHARACTERS))
        monkeypatch.setattr(store, "profile_roles", AsyncMock(return_value={CATEGORY: [51]}))
        monkeypatch.setattr(store, "category_roles", AsyncMock(return_value=(CATEGORY, frozenset({51, 52}))))
        monkeypatch.setattr(store, "categories", AsyncMock(return_value=[CATEGORY]))
        monkeypatch.setattr(store, "save_assignments", AsyncMock())
        yield Transport(bot, guild, actor), player


@pytest.mark.parametrize("actor_role,admin", [(71, True), (72, True), (CACTUS, False)])
def test_dashboard_renders_relevant_actions_without_default_admin_visibility(monkeypatch, actor_role, admin):
    async def scenario():
        async with setup(monkeypatch, actor_role) as (transport, _):
            command = transport.bot.tree.get_command("rproles")
            assert command.guild_only and command.default_permissions is None and command.parameters == []
            await transport.command("rproles")
            labels = {item.label for item in transport.view.children}
            assert "Gérer les personnages" in labels
            assert ("Configurer les catégories" in labels) is admin
            assert ("Configurer les accès" in labels) is admin
            if admin:
                await transport.press("Configurer les accès")
                assert isinstance(transport.view.children[0], discord.ui.RoleSelect)

    asyncio.run(scenario())


def test_member_profiles_use_live_guild_metadata_and_show_empty_values(monkeypatch):
    async def scenario():
        async with setup(monkeypatch, None) as (transport, player):
            empty = store.Category(101, "Race", 20, "single")
            store.profile_roles.return_value = {CATEGORY: [51], empty: []}
            with pytest.raises(store.RoleError, match="accès"):
                await transport.command("rproles")
            await transport.command("rpprofile")
            assert isinstance(transport.view.children[0], discord.ui.UserSelect)
            await transport.select(discord.ui.UserSelect, [player])
            await transport.select(discord.ui.Select, ["1"])
            assert transport.embed.title == "Néréide"
            assert transport.embed.thumbnail.url == CHARACTERS[0].image_url
            assert transport.embed.footer.text == "MinamixBot"
            assert "n:" in transport.embed.description
            assert transport.embed.colour.value == 0x9488AA
            assert transport.embed.fields[0].value == "• Lyndera"
            assert transport.embed.fields[1].value == "Non renseigné"
            assert all(not isinstance(item, discord.ui.Select) for item in transport.view.children)

            transport.guild.get_role(51).name = "Lyndera du Nord"
            await transport.press("Actualiser")
            assert transport.embed.fields[0].value == "• Lyndera du Nord"
            transport.guild._remove_role(51)
            await transport.press("Actualiser")
            assert "indisponible" in transport.embed.fields[0].value
            await transport.press("Personnage suivant")
            assert transport.embed.title == "Orion"
            await transport.press("Personnages")
            assert transport.embed.title == "Choisir un personnage"

    asyncio.run(scenario())


def test_validator_edits_by_character_preview_then_save_and_old_view_cannot_repeat(monkeypatch):
    async def scenario():
        async with setup(monkeypatch, CACTUS) as (transport, player):
            await transport.command("rproles")
            await transport.press("Gérer les personnages")
            await transport.select(discord.ui.UserSelect, [player])
            await transport.select(discord.ui.Select, ["2"])
            await transport.select(discord.ui.Select, [str(CATEGORY.id)])
            await transport.select(discord.ui.Select, ["52"])
            await transport.press("Prévisualiser")
            preview = transport.view
            assert transport.embed.fields[0].value == "• Silfus"
            store.save_assignments.assert_not_awaited()
            await transport.press("Enregistrer")
            store.save_assignments.assert_awaited_once_with(
                GUILD, store.Actor(42, False, frozenset({GUILD, CACTUS})), 3, player.id,
                CHARACTERS[1].id, CATEGORY.id, {51, 52}, {role.id: role for role in transport.guild.roles},
            )
            assert preview.is_finished()
            repeated = await transport.press("Enregistrer", view=preview)
            assert "expiré" in repeated.response.send_message.await_args.args[0]
            assert store.save_assignments.await_count == 1

    asyncio.run(scenario())


def test_permissions_are_rechecked_during_sessions_and_before_writes(monkeypatch):
    async def scenario():
        async with setup(monkeypatch, 72) as (transport, player):
            await transport.command("rproles")
            old_dashboard = transport.view
            validator = member(transport.guild, transport.actor.id, [CACTUS])
            with pytest.raises(store.RoleError, match="réservée"):
                await transport.press("Configurer les catégories", actor=validator)
            assert transport.view is old_dashboard
            await transport.press("Gérer les personnages", actor=validator)
            transport.actor = validator
            await transport.select(discord.ui.UserSelect, [player])
            await transport.select(discord.ui.Select, ["1"])
            await transport.select(discord.ui.Select, [str(CATEGORY.id)])
            await transport.press("Vider la catégorie")
            await transport.press("Prévisualiser")
            revoked = member(transport.guild, transport.actor.id)
            discord.Guild.fetch_member.return_value = revoked
            with pytest.raises(store.RoleError, match="accès"):
                await transport.press("Enregistrer")
            store.save_assignments.assert_not_awaited()
            with pytest.raises(store.RoleError, match="accès"):
                await transport.press("Annuler", actor=revoked)

    asyncio.run(scenario())


def test_category_flow_reuses_native_roles_and_confirms_impact(monkeypatch):
    async def scenario():
        async with setup(monkeypatch, 72) as (transport, _):
            monkeypatch.setattr(store, "affected_characters", AsyncMock(return_value=3))
            monkeypatch.setattr(store, "remove_category_or_link", AsyncMock())
            await transport.command("rproles")
            await transport.press("Configurer les catégories")
            await transport.select(discord.ui.Select, [str(CATEGORY.id)])
            assert isinstance(transport.view.children[0], discord.ui.RoleSelect)
            await transport.select(discord.ui.Select, ["51"], row=1)
            assert "3 personnage(s)" in transport.embed.description
            store.remove_category_or_link.assert_not_awaited()
            await transport.press("Annuler")
            assert transport.embed.title == "Pays"
            await transport.press("Supprimer la catégorie")
            assert "3 personnage(s)" in transport.embed.description
            await transport.press("Supprimer")
            store.remove_category_or_link.assert_awaited_once()
            assert store.remove_category_or_link.await_args.args[2:] == (3, CATEGORY.id, 3)

    asyncio.run(scenario())


def test_profiles_paginate_category_fields_and_character_selector(monkeypatch):
    async def scenario():
        async with setup(monkeypatch, None) as (transport, player):
            chars = [store.Character(i + 1, f"Personnage {i + 1}", "p:", "") for i in range(26)]
            store.list_characters.return_value = chars
            store.profile_roles.return_value = {
                store.Category(i, f"Catégorie {i}", i, "single"): [] for i in range(6)
            }
            await transport.command("rpprofile")
            await transport.select(discord.ui.UserSelect, [player])
            first_options = transport.view.children[0].options
            assert len(first_options) == 25
            await transport.press("Suivant ▶")
            assert [option.value for option in transport.view.children[0].options] == ["26"]
            await transport.select(discord.ui.Select, ["26"])
            assert len(transport.embed.fields) == 4
            await transport.press("Suivant ▶")
            assert len(transport.embed.fields) == 2
            assert "Catégorie 5" in {field.name for field in transport.embed.fields}

    asyncio.run(scenario())


def test_long_role_lists_are_split_into_discord_sized_fields():
    roles = {
        index: SimpleNamespace(name="🤍" * 30 + "_" * 40)
        for index in range(1, 26)
    }
    fields = profile_fields({CATEGORY: roles.keys()}, roles)
    assert len(fields) > 1
    assert {role_id for _, _, ids in fields for role_id in ids} == set(roles)
    assert all(len(description.encode("utf-16-le")) <= 2048 for _, description, _ in fields)


def test_admin_creates_category_from_modal_and_import_requires_confirmation(monkeypatch):
    from src.utils.rp_role_seed import AURUM_ROLES

    async def scenario():
        async with setup(monkeypatch, 71) as (transport, _):
            monkeypatch.setattr(store, "save_category", AsyncMock(return_value=CATEGORY.id))
            monkeypatch.setattr(store, "import_initial", AsyncMock())
            await transport.command("rproles")
            await transport.press("Configurer les catégories")
            inter = await transport.press("Créer une catégorie")
            inter.response.defer.assert_not_awaited()
            modal = inter.response.send_modal.await_args.args[0]
            modal.category_name._value = "Origine"
            modal.position._value = "5"
            submit = transport.interaction()
            assert await modal.interaction_check(submit)
            await modal.on_submit(submit)
            store.save_category.assert_awaited_once()
            assert store.save_category.await_args.kwargs == {
                "name": "Origine", "position": 5, "mode": "single", "category_id": None,
            }
            await transport.press("Catégories")
            with pytest.raises(store.RoleError, match="introuvables"):
                await transport.press("Importer les rôles RP initiaux")
            store.import_initial.assert_not_awaited()
            role_ids = [role_id for _, _, linked in AURUM_ROLES for role_id in linked]
            discord.Guild.fetch_roles.return_value = [
                SimpleNamespace(id=role_id, name=f"Rôle {i}") for i, role_id in enumerate(role_ids)
            ]
            await transport.press("Importer les rôles RP initiaux")
            assert "6 catégories et 24 rôles" in transport.embed.description
            assert len(transport.embed.fields) == 6
            store.import_initial.assert_not_awaited()
            await transport.press("Importer")
            store.import_initial.assert_awaited_once()
            args = store.import_initial.await_args.args
            assert args[:4] == (GUILD, store.Actor.from_member(transport.actor), 3, AURUM_ROLES)
            assert args[4].keys() == set(role_ids)

    asyncio.run(scenario())
