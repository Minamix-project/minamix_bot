import discord


class ExpiringView(discord.ui.View):
    def __init__(self, timeout: float = 60, *, owner_id: int | None = None):
        super().__init__(timeout=timeout)
        self.message: discord.Message | None = None
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.owner_id is None or interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "❌ Cette interaction ne t'appartient pas.", ephemeral=True
        )
        return False

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(
                    content="⏱️ Cette sélection a expiré.",
                    embed=None,
                    view=None,
                )
            except (discord.HTTPException, discord.NotFound):
                return
