"""Public command entry points for character profiles and restricted RP role management."""

import discord
from discord import app_commands

from src.utils.command_errors import ERROR_HANDLED_KEY
from src.utils.rp_role_admin import AdminRoleMenu
from src.utils.rp_role_profiles import CharacterMenu
from src.utils.rp_role_ui import RoleSession, RoleView, ui_error


async def register(bot):
    @bot.tree.command(name="rproles", description="Gérer les rôles RP des personnages.")
    @app_commands.guild_only()
    async def rproles(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        session = RoleSession(interaction, management=True)

        async def dashboard(inter):
            actor = await session.authorize(inter)
            view = RoleView(session, inter, "Gestion des rôles RP")
            view.button("Gérer les personnages", characters.members, row=0, style=discord.ButtonStyle.primary)
            if actor.admin:
                view.button("Configurer les catégories", admin.categories, row=0)
                view.button("Configurer les accès", admin.access, row=0)
            view.button("Fermer", session.close)
            await session.show(inter, view)

        characters = CharacterMenu(session, dashboard=dashboard)
        admin = AdminRoleMenu(session, dashboard)
        await dashboard(interaction)

    @bot.tree.command(name="rpprofile", description="Consulter la fiche et les attributs d'un personnage RP.")
    @app_commands.guild_only()
    async def rpprofile(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        session = RoleSession(interaction)
        await session.authorize(interaction)
        await CharacterMenu(session).members(interaction)

    async def command_error(interaction, error):
        original = error.original if isinstance(error, app_commands.CommandInvokeError) else error
        await ui_error(interaction, original)
        interaction.extras[ERROR_HANDLED_KEY] = True

    rproles.error(command_error)
    rpprofile.error(command_error)
