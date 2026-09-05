import asyncio
from types import SimpleNamespace

from src.utils.views import ExpiringView


class _Response:
    def __init__(self):
        self.messages = []

    async def send_message(self, content, *, ephemeral):
        self.messages.append((content, ephemeral))


def test_view_accepts_its_owner():
    async def run_test():
        view = ExpiringView(owner_id=42)
        interaction = SimpleNamespace(user=SimpleNamespace(id=42), response=_Response())
        assert await view.interaction_check(interaction)

    asyncio.run(run_test())


def test_view_rejects_another_user():
    async def run_test():
        view = ExpiringView(owner_id=42)
        response = _Response()
        interaction = SimpleNamespace(user=SimpleNamespace(id=99), response=response)
        assert not await view.interaction_check(interaction)
        assert response.messages == [("❌ Cette interaction ne t'appartient pas.", True)]

    asyncio.run(run_test())
