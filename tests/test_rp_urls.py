from src.utils.rp import normalize_discord_image_url


def test_discord_attachment_signature_is_removed():
    url = "https://cdn.discordapp.com/attachments/123/456/avatar.png?ex=abc&is=def&hm=signature"
    assert normalize_discord_image_url(url) == "https://cdn.discordapp.com/attachments/123/456/avatar.png"


def test_non_discord_urls_are_preserved():
    url = "https://example.test/avatar.png?token=keep"
    assert normalize_discord_image_url(url) == url
