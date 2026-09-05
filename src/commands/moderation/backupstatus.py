import json
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import Interaction
from src.utils.permissions import admin_only

STATUS_FILE = Path("backup_test_status/last_restore_test.json")


def _read_restore_test_status() -> dict | None:
    if not STATUS_FILE.exists():
        return None
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


async def register(bot):
    @bot.tree.command(name="backupstatus", description="Voir la dernière sauvegarde (Admin seulement)")
    @admin_only()
    async def backupstatus(interaction: Interaction):
        backups = list(Path("backups").glob("*.sql"))
        if not backups:
            await interaction.response.send_message("❌ Aucun dump SQL trouvé.", ephemeral=True)
            return
        latest = max(backups, key=lambda path: path.stat().st_mtime)
        modified = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)

        lines = [
            f"💾 Dernier dump : `{latest.name}`",
            f"Date : <t:{int(modified.timestamp())}:F>",
            f"Taille : `{latest.stat().st_size:,}` octets",
        ]

        test_status = _read_restore_test_status()
        if test_status is None:
            lines.append("\n⚠️ Aucun test de restauration disponible pour l'instant.")
        else:
            icon = {"ok": "✅", "fail": "❌", "no_backup": "⚠️"}.get(test_status.get("status"), "❔")
            lines.append(
                f"\n{icon} **Test de restauration** ({test_status.get('file') or '—'})\n"
                f"{test_status.get('detail', '')}\n"
                f"Testé le : {test_status.get('tested_at', '—')}"
            )

        await interaction.response.send_message("\n".join(lines), ephemeral=True)
