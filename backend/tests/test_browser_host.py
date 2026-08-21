from backend.core.browser_host import canonical_browser_host, valid_browser_host


def test_canonical_host_prefers_configured_value() -> None:
    assert (
        canonical_browser_host(
            configured="console.example:443",
            forwarded_host="evil.example",
            request_host="evil.example",
        )
        == "console.example:443"
    )


def test_canonical_host_allows_loopback_when_unconfigured() -> None:
    assert (
        canonical_browser_host(
            configured=None,
            forwarded_host=None,
            request_host="127.0.0.1:3000",
        )
        == "127.0.0.1:3000"
    )


def test_canonical_host_rejects_public_host_when_unconfigured() -> None:
    assert (
        canonical_browser_host(
            configured=None,
            forwarded_host="evil.example",
            request_host="evil.example",
        )
        is None
    )


def test_valid_browser_host_rejects_url_shaped_values() -> None:
    assert valid_browser_host("console.example") is True
    assert valid_browser_host("https://evil.example") is False
    assert valid_browser_host("evil.example/callback") is False
    assert valid_browser_host("user@evil.example") is False
