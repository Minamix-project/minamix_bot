"""Explicit reminder date parsing, independent of the host timezone."""

from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Europe/Brussels"
_DURATION = re.compile(r"(\d+)\s*(sem|[smhjdw])", re.IGNORECASE)
_SECONDS = {"s": 1, "m": 60, "h": 3600, "j": 86400, "sem": 604800, "d": 86400, "w": 604800}


def parse_reminder_time(value: str, timezone_name: str = DEFAULT_TIMEZONE, *, now: datetime | None = None) -> int:
    """Return a UTC Unix timestamp for a duration, day + time, date, or time.

    Ambiguous and nonexistent local times are rejected instead of guessing at
    daylight-saving transitions. Durations always represent elapsed time.
    """
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Fuseau horaire inconnu. Utilise un nom IANA comme Europe/Brussels ou UTC.") from exc
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("L'heure de référence doit inclure un fuseau horaire.")
    raw = value.strip().lower()
    parts = list(_DURATION.finditer(raw))
    if parts and not _DURATION.sub("", raw).strip():
        seconds = sum(int(part[1]) * _SECONDS[part[2].lower()] for part in parts)
        timestamp = int(now.timestamp()) + seconds
    else:
        local_now = now.astimezone(zone)
        tokens = raw.split()
        try:
            if len(tokens) == 1 and re.fullmatch(r"\d{1,2}:\d{2}", raw):
                naive = datetime.combine(local_now.date(), datetime.strptime(raw, "%H:%M").time())
            elif len(tokens) == 2 and tokens[0] in {"today", "tomorrow", "aujourd'hui", "demain"}:
                days = int(tokens[0] in {"tomorrow", "demain"})
                date = local_now.date() + timedelta(days=days)
                naive = datetime.combine(date, datetime.strptime(tokens[1], "%H:%M").time())
            else:
                pattern = "%d/%m/%Y %H:%M" if "/" in raw else "%Y-%m-%d %H:%M"
                naive = datetime.strptime(raw, pattern)
        except (ValueError, OverflowError) as exc:
            raise ValueError("Utilise 2h, 1j 30m, demain 18:00, HH:MM ou JJ/MM/AAAA HH:MM.") from exc

        candidates = set()
        for fold in (0, 1):
            candidate = naive.replace(tzinfo=zone, fold=fold)
            utc = candidate.astimezone(timezone.utc)
            if utc.astimezone(zone).replace(tzinfo=None) == naive:
                candidates.add(int(utc.timestamp()))
        if len(candidates) != 1:
            raise ValueError("Cette heure est ambiguë ou inexistante à cause du changement d'heure. Utilise UTC.")
        timestamp = candidates.pop()

    if timestamp <= now.timestamp():
        raise ValueError("Le rappel doit être dans le futur. Une heure sans date correspond à aujourd'hui.")
    if timestamp > int(now.timestamp()) + 5 * 366 * 86400:
        raise ValueError("Les rappels peuvent être programmés au maximum cinq ans à l'avance.")
    return timestamp
