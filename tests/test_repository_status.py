"""Pinned main statistics, release filtering, caching and public /status fallback."""

import asyncio
import io
import json
import tarfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.error import HTTPError, URLError

import discord
import pytest

from src.commands.moderation import status as command
from src.utils import repository_status as repository

REVISION = "a" * 40


def archive(files):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as result:
        for name, content in files.items():
            data = content.encode() if isinstance(content, str) else content
            member = tarfile.TarInfo("repo-commit/" + name)
            member.size = len(data)
            result.addfile(member, io.BytesIO(data))
    return output.getvalue()


def stats():
    return repository.RepositoryStats(REVISION, 12345, 123, 157, ("Python", "SQL"), "v1.9.0")


def test_source_counts_exclude_binary_and_documentation_lines_without_extracting_files():
    lines, files, languages = repository.archive_statistics(
        archive(
            {
                "src/bot.py": "# Comment\n\nprint('été')\n",
                "src/db.sql": "SELECT 1;\n\n",
                "README.md": "Documentation\n",
                "assets/image.png": b"\xff\x00",
                "Dockerfile": "FROM python\n",
            }
        )
    )
    assert (lines, files) == (4, 5)
    assert languages == ("Python", "Dockerfile", "SQL")


def test_archive_reading_has_resource_limits(monkeypatch):
    monkeypatch.setattr(repository, "MAX_FILES", 1)
    with pytest.raises(ValueError, match="resource limits"):
        repository.archive_statistics(archive({"first.py": "one", "second.py": "two"}))


@pytest.mark.parametrize("path", [f"/repos/{repository.REPOSITORY}/commits", "/repositories/1247022598/commits"])
def test_commit_count_supports_named_and_canonical_github_pagination(monkeypatch, path):
    link = f'<https://api.github.com{path}?page=157&per_page=1>; rel="last"'
    monkeypatch.setattr(repository, "_json", Mock(return_value=([{"sha": REVISION}], {"Link": link})))
    assert repository._commit_count(REVISION) == 157
    assert f"sha={REVISION}" in repository._json.call_args.args[0]


def test_all_statistics_are_pinned_to_one_main_revision_and_do_not_require_git(monkeypatch):
    calls = []

    def request(path, **kwargs):
        calls.append(path)
        data = {
            "branches/main": {"commit": {"sha": REVISION}},
            f"commits?sha={REVISION}&per_page=1": [{"sha": REVISION}],
            "releases/latest": {"target_commitish": "main", "tag_name": "v1.9.0"},
        }
        if path.startswith("tarball/"):
            return archive({"bot.py": "print('ok')\n"}), {}
        return json.dumps(data[path]).encode(), {}

    monkeypatch.setattr(repository, "_request", request)
    result = repository.fetch_repository_stats()
    assert (result.revision, result.lines, result.files, result.commits) == (REVISION, 1, 1, 1)
    assert result.release == "v1.9.0" and result.release_available
    assert f"tarball/{REVISION}" in calls


def test_latest_version_excludes_other_branches_drafts_and_prereleases(monkeypatch):
    request = Mock(
        side_effect=[
            ({"target_commitish": "preview", "tag_name": "v9.0.0"}, {}),
            (
                [
                    {"target_commitish": "main", "tag_name": "v1.9.0", "published_at": "2026-11-04"},
                    {"target_commitish": "preview", "tag_name": "v9.0.0", "published_at": "2026-11-10"},
                    {"target_commitish": "main", "tag_name": "v2.0.0", "published_at": "2026-11-10", "draft": True},
                    {
                        "target_commitish": "main",
                        "tag_name": "v3.0.0",
                        "published_at": "2026-11-10",
                        "prerelease": True,
                    },
                ],
                {},
            ),
        ]
    )
    monkeypatch.setattr(repository, "_json", request)
    assert repository._latest_main_release() == "v1.9.0"


def test_no_published_release_is_distinct_from_an_api_failure(monkeypatch):
    monkeypatch.setattr(repository, "_json", Mock(side_effect=HTTPError("url", 404, "Missing", {}, None)))
    assert repository._latest_main_release() is None
    monkeypatch.setattr(repository, "_json", Mock(side_effect=HTTPError("url", 403, "Limited", {}, None)))
    with pytest.raises(HTTPError):
        repository._latest_main_release()


def test_cache_shares_concurrent_requests_and_preserves_the_last_result_during_an_outage(monkeypatch):
    async def scenario():
        fetch = Mock(return_value=stats())
        monkeypatch.setattr(repository, "fetch_repository_stats", fetch)
        cache = repository.RepositoryCache()
        results = await asyncio.gather(*(cache.get() for _ in range(4)))
        fetch.assert_called_once()
        assert all(result.stats == stats() and not result.stale for result in results)
        cache._refresh_at = 0
        fetch.side_effect = URLError("Unavailable")
        result = await cache.get()
        assert result.stats == stats() and result.stale
        assert (await cache.get()).stale and fetch.call_count == 2

    asyncio.run(scenario())


def test_cold_api_failure_is_throttled_and_returns_an_unavailable_result(monkeypatch):
    async def scenario():
        fetch = Mock(side_effect=URLError("Unavailable"))
        monkeypatch.setattr(repository, "fetch_repository_stats", fetch)
        cache = repository.RepositoryCache()
        assert (await cache.get()).stats is None
        assert (await cache.get()).stats is None
        fetch.assert_called_once()

    asyncio.run(scenario())


@pytest.mark.parametrize("available,stale", [(True, False), (True, True), (False, False)])
def test_status_displays_repository_fields_and_still_works_when_github_is_unavailable(monkeypatch, available, stale):
    async def scenario():
        callbacks = {}

        def register(**options):
            def decorator(callback):
                callbacks[options["name"]] = callback
                return callback

            return decorator

        user = discord.ClientUser(
            state=None, data={"id": "99", "username": "Aurum", "discriminator": "0", "avatar": None}
        )
        bot = SimpleNamespace(
            tree=SimpleNamespace(command=register),
            user=user,
            latency=0.12,
            guilds=[SimpleNamespace(member_count=10), SimpleNamespace(member_count=None)],
        )
        interaction = SimpleNamespace(
            client=bot, response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock())
        )
        monkeypatch.setattr(
            command,
            "get_repository_status",
            AsyncMock(return_value=repository.RepositoryResult(stats() if available else None, stale=stale)),
        )
        await command.register(bot)
        await callbacks["status"](interaction)
        embed = interaction.followup.send.await_args.kwargs["embed"]
        fields = {field.name: field.value for field in embed.fields}
        assert fields["Ping"] == "`120 ms`" and fields["Membres"] == "`10`"
        for name in ("Lignes de code", "Fichiers", "Commits", "Langages", "Dernière version (main)"):
            assert name in fields
        if available:
            assert fields["Lignes de code"] == "12 345"
            assert fields["Fichiers"] == "123" and fields["Commits"] == "157"
            assert fields["Langages"] == "2 — Python, SQL"
            assert "v1.9.0" in fields["Dernière version (main)"]
        else:
            assert fields["Lignes de code"] == "Indisponible" and "Actualisation" in fields
        if stale:
            assert "conservées" in fields["Actualisation"]
        assert len(embed) <= 6000

    asyncio.run(scenario())
