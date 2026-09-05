import importlib
import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def load_modules(bot, directory: str, label: str):
    base = Path(directory)
    if not base.exists():
        logger.warning("Directory '%s' not found", directory)
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
                logger.info("[%s] %s", label, module_name)
        except Exception:
            logger.exception("Could not load %s", module_name)
            raise
