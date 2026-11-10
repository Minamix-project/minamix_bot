"""Bounded, cached public repository statistics pinned to the main branch."""

import asyncio
from dataclasses import dataclass
import io
import json
import logging
import re
import tarfile
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import Request, urlopen


REPOSITORY = "Minamix-project/minamix_bot"
API_ROOT = f"https://api.github.com/repos/{REPOSITORY}"
WEB_ROOT = f"https://github.com/{REPOSITORY}"
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_FILES = 10000
CACHE_SECONDS = 600
RETRY_SECONDS = 120
LANGUAGE_SUFFIXES = {
    ".py": "Python",
    ".pyi": "Python",
    ".sql": "SQL",
    ".html": "HTML",
    ".css": "CSS",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".toml": "TOML",
    ".json": "JSON",
    ".sh": "Shell",
}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RepositoryStats:
    revision: str
    lines: int
    files: int
    commits: int
    languages: tuple[str, ...]
    release: str | None
    release_available: bool = True

    @property
    def release_url(self):
        return f"{WEB_ROOT}/releases/tag/{quote(self.release, safe='')}" if self.release else None


@dataclass(frozen=True)
class RepositoryResult:
    stats: RepositoryStats | None
    stale: bool = False


def _request(path, *, limit=2 * 1024 * 1024):
    request = Request(
        f"{API_ROOT}/{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Aurum-Repository-Status",
        },
    )
    with urlopen(request, timeout=8) as response:
        content = response.read(limit + 1)
        if len(content) > limit:
            raise ValueError("Repository response exceeds its size limit")
        return content, response.headers


def _json(path):
    content, headers = _request(path)
    return json.loads(content), headers


def archive_statistics(content):
    """Count tracked files and nonblank source/config lines without extracting files."""
    files = lines = source_bytes = 0
    languages = {}
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
        for member in archive:
            if not (member.isfile() or member.issym()):
                continue
            files += 1
            source_bytes += member.size
            if files > MAX_FILES or source_bytes > MAX_SOURCE_BYTES:
                raise ValueError("Repository archive exceeds its resource limits")
            parts = member.name.split("/")
            if len(parts) < 2 or ".." in parts:
                raise ValueError("Unexpected repository archive path")
            filename = parts[-1]
            language = {"Dockerfile": "Dockerfile", "Makefile": "Makefile"}.get(filename)
            if language is None:
                language = LANGUAGE_SUFFIXES.get("." + filename.rsplit(".", 1)[-1].lower())
            if not language or not member.isfile():
                continue
            file = archive.extractfile(member)
            if file is None:
                continue
            with file:
                text = file.read().decode("utf-8-sig")
            count = sum(bool(line.strip()) for line in text.splitlines())
            lines += count
            languages[language] = languages.get(language, 0) + count
    return lines, files, tuple(sorted(languages, key=lambda name: (-languages[name], name)))


def _commit_count(revision):
    commits, headers = _json(f"commits?sha={revision}&per_page=1")
    if not isinstance(commits, list) or len(commits) != 1 or commits[0].get("sha") != revision:
        raise ValueError("Unexpected main commit response")
    link = headers.get("Link", "")
    last = re.search(r'<([^>]+)>;\s*rel="last"', link)
    if last:
        url = urlsplit(last[1])
        valid_path = url.path == f"/repos/{REPOSITORY}/commits" or re.fullmatch(
            r"/repositories/[0-9]+/commits", url.path
        )
        if url.hostname != "api.github.com" or not valid_path:
            raise ValueError("Unexpected commit pagination URL")
        count = int(parse_qs(url.query)["page"][0])
        if count < 1:
            raise ValueError("Invalid commit count")
        return count
    if link:
        raise ValueError("Commit pagination does not expose an exact count")
    return 1


def _latest_main_release():
    try:
        latest, _headers = _json("releases/latest")
    except HTTPError as error:
        if error.code == 404:
            return None
        raise
    if not isinstance(latest, dict):
        raise ValueError("Unexpected release response")
    releases = [latest]
    if latest.get("target_commitish") != "main":
        releases, _headers = _json("releases?per_page=100")
        if not isinstance(releases, list):
            raise ValueError("Unexpected releases response")
    eligible = [
        release
        for release in releases
        if release.get("target_commitish") == "main"
        and not release.get("draft")
        and not release.get("prerelease")
        and release.get("tag_name")
    ]
    if not eligible:
        return None
    release = max(eligible, key=lambda value: value.get("published_at") or "")["tag_name"]
    if not isinstance(release, str) or len(release) > 128 or not release.isprintable():
        raise ValueError("Invalid release tag")
    return release


def fetch_repository_stats():
    branch, _headers = _json("branches/main")
    if not isinstance(branch, dict) or not isinstance(branch.get("commit"), dict):
        raise ValueError("Unexpected main branch response")
    revision = branch["commit"].get("sha")
    if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", revision):
        raise ValueError("Invalid main revision")
    commits = _commit_count(revision)
    content, _headers = _request(f"tarball/{revision}", limit=MAX_ARCHIVE_BYTES)
    lines, files, languages = archive_statistics(content)
    release_available = True
    try:
        release = _latest_main_release()
    except (OSError, ValueError):
        release, release_available = None, False
    return RepositoryStats(revision, lines, files, commits, languages, release, release_available)


class RepositoryCache:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._result = RepositoryResult(None)
        self._refresh_at = 0.0

    async def get(self):
        async with self._lock:
            now = time.monotonic()
            if now < self._refresh_at:
                return self._result
            try:
                stats = await asyncio.wait_for(asyncio.to_thread(fetch_repository_stats), timeout=25)
            except (OSError, ValueError, tarfile.TarError) as error:
                logger.warning("Could not fetch repository statistics type=%s", type(error).__name__)
                self._result = RepositoryResult(self._result.stats, stale=self._result.stats is not None)
                self._refresh_at = time.monotonic() + RETRY_SECONDS
            else:
                self._result = RepositoryResult(stats)
                self._refresh_at = time.monotonic() + CACHE_SECONDS
            return self._result


_cache = RepositoryCache()


async def get_repository_status():
    return await _cache.get()
