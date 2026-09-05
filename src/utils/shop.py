from discord import app_commands
from src.utils.db import get_db_connection
from src.utils.format import format_amount


async def get_shop_items(guild_id: int):
    db = await get_db_connection()
    try:
        async with db.cursor() as cursor:
            await cursor.execute("SELECT id, role_id, prix, nom, description, exclusif FROM guild_boutique_roles WHERE guild_id = %s ORDER BY exclusif ASC, id ASC", (guild_id,))
            return (await cursor.fetchall())
    finally:
        db.close()


async def item_autocomplete(interaction, current: str):
    """Shared autocomplete for commands taking an item number (/buy, /edititem, /removeitem, /giveitem)."""
    items = await get_shop_items(interaction.guild_id)
    current = (current or "").lower()
    choices = []
    for num, (_id, _role_id, prix, nom, *_rest) in enumerate(items, start=1):
        if current in nom.lower() or current in str(num):
            choices.append(app_commands.Choice(name=f"#{num} — {nom} ({format_amount(prix)}💰)", value=str(num)))
    return choices[:25]
