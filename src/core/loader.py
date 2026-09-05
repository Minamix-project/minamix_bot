import importlib
import asyncio
from pathlib import Path


async def load_modules(bot, directory: str, label: str):
    base = Path(directory)
    if not base.exists():
        print(f"[WARN] Dossier '{directory}' introuvable.")
        return

    for path in sorted(base.rglob("*.py")):
        if path.name.startswith("_"):
            continue

        rel = path.relative_to("src")
        module_name = f"src.{rel.with_suffix('').as_posix().replace('/', '.')}"

        try:
            module = importlib.import_module(module_name)
            if hasattr(module, "register"):
                fn = module.register
                await fn(bot) if asyncio.iscoroutinefunction(fn) else fn(bot)
                print(f"[{label}] {module_name}")
        except Exception as e:
            print(f"[ERREUR] {module_name}: {e}")
            raise
