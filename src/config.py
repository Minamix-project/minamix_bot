import os


_DEFAULT_GUILD_IDS = [
    1437105431741730860,
    1482529716463210506,
]


def _integer_set_from_env(name: str, defaults: list[int]) -> set[int]:
    raw = os.getenv(name)
    if not raw:
        return set(defaults)
    try:
        values = {int(value.strip()) for value in raw.split(",") if value.strip()}
    except ValueError as exc:
        raise RuntimeError(f"{name} must contain only comma-separated IDs") from exc
    if not values:
        raise RuntimeError(f"{name} cannot be empty")
    return values


GUILD_IDS = _integer_set_from_env("DISCORD_GUILD_IDS", _DEFAULT_GUILD_IDS)
