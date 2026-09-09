from src.utils.permissions import admin_only
from discord import Interaction, app_commands
import discord
from src.utils.embed import set_bot_footer
from src.utils.format import format_amount
from src.utils.economy_config import get_guild_economy_config, update_guild_economy_config


def _config_lines(config: dict) -> list[str]:
    cap = config["balance_cap"]
    cooldown_h = config["work_cooldown_seconds"] / 3600
    return [
        f"**Gain /work :** {config['work_gain_min']} – {config['work_gain_max']}💰",
        f"**Délai de récupération /work :** {cooldown_h:.1f}h",
        f"**Gain par message :** {config['message_gain_min']} – {config['message_gain_max']}💰",
        f"**Gain par message (≥1000 caractères) :** {config['message_gain_long_min']} – {config['message_gain_long_max']}💰",
        f"**Solde initial :** {format_amount(config['starting_balance'])}💰",
        f"**Plafond :** {format_amount(cap) + '💰' if cap is not None else 'Aucun'}",
        f"**Transferts 💰 :** délai {config['transfer_cooldown_seconds'] // 60} min · limite/jour {format_amount(config['transfer_daily_limit'])}💰",
        f"**Transferts NAX :** délai {config['nax_transfer_cooldown_seconds'] // 60} min · limite/jour {format_amount(config['nax_transfer_daily_limit'])} NAX",
    ]


async def register(bot):
    @bot.tree.command(
        name="economyconfig",
        description="Configurer l'économie de ce serveur (Admin seulement)"
    )
    @app_commands.describe(
        work_gain_min="Gain minimum de /work",
        work_gain_max="Gain maximum de /work",
        work_cooldown_minutes="Délai de récupération de /work, en minutes",
        message_gain_min="Gain minimum par message",
        message_gain_max="Gain maximum par message",
        message_gain_long_min="Gain minimum par message long (≥1000 caractères)",
        message_gain_long_max="Gain maximum par message long (≥1000 caractères)",
        starting_balance="Solde initial d'un nouveau membre",
        balance_cap="Plafond de solde (0 = aucun plafond)",
        transfer_cooldown_minutes="Délai entre deux transferts 💰, en minutes (0 = désactivé)",
        transfer_daily_limit="Maximum transférable en 💰 par jour (0 = désactivé)",
        nax_transfer_cooldown_minutes="Délai entre deux transferts NAX, en minutes (0 = désactivé)",
        nax_transfer_daily_limit="Maximum transférable en NAX par jour (0 = désactivé)",
    )
    @admin_only()
    async def economyconfig(
        interaction: Interaction,
        work_gain_min: int = None,
        work_gain_max: int = None,
        work_cooldown_minutes: int = None,
        message_gain_min: int = None,
        message_gain_max: int = None,
        message_gain_long_min: int = None,
        message_gain_long_max: int = None,
        starting_balance: int = None,
        balance_cap: int = None,
        transfer_cooldown_minutes: int = None,
        transfer_daily_limit: int = None,
        nax_transfer_cooldown_minutes: int = None,
        nax_transfer_daily_limit: int = None,
    ):
        invalid = None
        non_negative_values = {
            "work_gain_min": work_gain_min,
            "work_gain_max": work_gain_max,
            "message_gain_min": message_gain_min,
            "message_gain_max": message_gain_max,
            "message_gain_long_min": message_gain_long_min,
            "message_gain_long_max": message_gain_long_max,
            "starting_balance": starting_balance,
            "balance_cap": balance_cap,
            "transfer_cooldown_minutes": transfer_cooldown_minutes,
            "transfer_daily_limit": transfer_daily_limit,
            "nax_transfer_cooldown_minutes": nax_transfer_cooldown_minutes,
            "nax_transfer_daily_limit": nax_transfer_daily_limit,
        }
        for field, value in non_negative_values.items():
            if value is not None and value < 0:
                invalid = f"`{field}` ne peut pas être négatif."
                break
        if work_cooldown_minutes is not None and work_cooldown_minutes <= 0:
            invalid = "`work_cooldown_minutes` doit être supérieur à zéro."

        if invalid is not None:
            embed = discord.Embed(
                title="❌ Configuration invalide",
                description=invalid,
                color=discord.Color.red(),
            )
            set_bot_footer(embed, interaction)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        changes = {}
        if work_gain_min is not None:
            changes["work_gain_min"] = work_gain_min
        if work_gain_max is not None:
            changes["work_gain_max"] = work_gain_max
        if work_cooldown_minutes is not None:
            changes["work_cooldown_seconds"] = work_cooldown_minutes * 60
        if message_gain_min is not None:
            changes["message_gain_min"] = message_gain_min
        if message_gain_max is not None:
            changes["message_gain_max"] = message_gain_max
        if message_gain_long_min is not None:
            changes["message_gain_long_min"] = message_gain_long_min
        if message_gain_long_max is not None:
            changes["message_gain_long_max"] = message_gain_long_max
        if starting_balance is not None:
            changes["starting_balance"] = starting_balance
        if balance_cap is not None:
            changes["balance_cap"] = balance_cap if balance_cap > 0 else None
        if transfer_cooldown_minutes is not None:
            changes["transfer_cooldown_seconds"] = transfer_cooldown_minutes * 60
        if transfer_daily_limit is not None:
            changes["transfer_daily_limit"] = transfer_daily_limit
        if nax_transfer_cooldown_minutes is not None:
            changes["nax_transfer_cooldown_seconds"] = nax_transfer_cooldown_minutes * 60
        if nax_transfer_daily_limit is not None:
            changes["nax_transfer_daily_limit"] = nax_transfer_daily_limit

        if changes:
            current = await get_guild_economy_config(interaction.guild_id)
            for min_key, max_key in (
                ("work_gain_min", "work_gain_max"),
                ("message_gain_min", "message_gain_max"),
                ("message_gain_long_min", "message_gain_long_max"),
            ):
                lo = changes.get(min_key, current[min_key])
                hi = changes.get(max_key, current[max_key])
                if lo > hi:
                    embed = discord.Embed(
                        title="❌ Configuration invalide",
                        description=f"`{min_key}` ({lo}) ne peut pas dépasser `{max_key}` ({hi}).",
                        color=discord.Color.red(),
                    )
                    set_bot_footer(embed, interaction)
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return

            effective_start = changes.get("starting_balance", current["starting_balance"])
            effective_cap = changes.get("balance_cap", current["balance_cap"])
            if effective_cap is not None and effective_start > effective_cap:
                embed = discord.Embed(
                    title="❌ Configuration invalide",
                    description="Le solde initial ne peut pas dépasser le plafond.",
                    color=discord.Color.red(),
                )
                set_bot_footer(embed, interaction)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            config = await update_guild_economy_config(interaction.guild_id, **changes)
            title = "✅ Configuration économique mise à jour"
        else:
            config = await get_guild_economy_config(interaction.guild_id)
            title = "⚙️ Configuration économique"

        embed = discord.Embed(title=title, description="\n".join(_config_lines(config)), color=discord.Color.blurple())
        set_bot_footer(embed, interaction)
        await interaction.response.send_message(embed=embed, ephemeral=True)
