"""Site branding API and asset safety tests."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("REFRAQ_SKIP_SEED", "1")

from backend.admin.audit_store import get_audit_store  # noqa: E402
from backend.admin.branding.service import (  # noqa: E402
    MAX_ASSET_BYTES,
    packaged_asset_bytes,
    reset_branding_cache,
)
from backend.admin.branding.store import (  # noqa: E402
    BrandingAssetKind,
    MemoryBrandingStore,
    get_branding_store,
)
from backend.tests.problem import assert_problem  # noqa: E402
from backend.admin.permissions import ALL_PERMISSIONS  # noqa: E402
from backend.admin.role_store import MemoryRoleStore, get_role_store  # noqa: E402
from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.session_store import (  # noqa: E402
    MemorySessionStore,
    get_session_store,
)
from backend.admin.user_store import MemoryUserStore, get_user_store  # noqa: E402
from backend.main import app  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"safe-png"
JPEG = b"\xff\xd8\xff\xe0" + b"safe-jpeg"
ICO = b"\x00\x00\x01\x00" + b"safe-ico"
SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2 2">'
    b'<path fill="#123456" d="M0 0h2v2H0z"/></svg>'
)
DEFAULT_PUBLIC = {
    "brand_names": {},
    "taglines": {},
    "primary_color": None,
    "primary_shades": None,
    "show_logo": True,
    "show_brand_name_with_logo": True,
    "logo_url": None,
    "favicon_url": None,
    "logo_source": None,
    "favicon_source": None,
}


@pytest.fixture
def stores():
    roles = MemoryRoleStore()
    seed_roles(roles)
    users = MemoryUserStore()
    root_role = roles.get_by_key("super_admin")
    operator_role = roles.get_by_key("operator")
    assert root_role is not None and operator_role is not None
    users.create_user(
        account="root",
        display_name="Root",
        password_hash=hash_password("s3cret"),
        role_id=root_role.id,
    )
    users.create_user(
        account="op",
        display_name="Operator",
        password_hash=hash_password("op-pass"),
        role_id=operator_role.id,
    )
    sessions = MemorySessionStore()
    branding = MemoryBrandingStore()
    app.dependency_overrides[get_user_store] = lambda: users
    app.dependency_overrides[get_role_store] = lambda: roles
    app.dependency_overrides[get_session_store] = lambda: sessions
    app.dependency_overrides[get_branding_store] = lambda: branding
    yield branding
    app.dependency_overrides.clear()


@pytest.fixture
def client(stores):
    with TestClient(app) as test_client:
        yield test_client


def _login(client: TestClient, account: str = "root", password: str = "s3cret") -> None:
    response = client.post(
        "/auth/login", json={"account": account, "password": password}
    )
    assert response.status_code == 200


def test_public_branding_is_unresolved_cacheable_and_supports_304(
    client: TestClient,
) -> None:
    default = client.get("/branding")
    assert default.status_code == 200
    assert default.json() == DEFAULT_PUBLIC
    assert "attribution" not in default.json()
    assert (
        default.headers["cache-control"]
        == "public, max-age=30, stale-while-revalidate=60"
    )
    etag = default.headers["etag"]
    unchanged = client.get("/branding", headers={"If-None-Match": etag})
    assert unchanged.status_code == 304
    assert unchanged.content == b""
    assert unchanged.headers["etag"] == etag


def test_put_preserves_unresolved_maps_trims_and_supports_present_null(
    client: TestClient,
) -> None:
    _login(client)
    shades = [f"#{index:06x}" for index in range(10)]
    response = client.put(
        "/branding",
        json={
            "brand_names": {"zh-CN": "  Acme China  ", "en-US": "Acme"},
            "taglines": {"zh-CN": "  Data works  "},
            "primary_color": " #AABBCC ",
            "primary_shades": shades,
            "show_logo": False,
            "show_brand_name_with_logo": False,
        },
    )
    assert response.status_code == 200
    assert response.headers["etag"]
    body = response.json()
    assert body["brand_names"] == {"zh-CN": "Acme China", "en-US": "Acme"}
    assert body["taglines"] == {"zh-CN": "Data works"}
    assert body["primary_color"] == "#aabbcc"
    assert body["primary_shades"] == shades
    assert body["show_logo"] is False
    assert body["show_brand_name_with_logo"] is False

    cleared = client.put(
        "/branding",
        json={"taglines": None, "primary_color": None, "primary_shades": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["taglines"] == {}
    assert cleared.json()["primary_color"] is None
    assert cleared.json()["brand_names"] == body["brand_names"]

    restored = client.put(
        "/branding",
        json={"show_logo": None, "show_brand_name_with_logo": None},
    )
    assert restored.status_code == 200
    assert restored.json()["show_logo"] is True
    assert restored.json()["show_brand_name_with_logo"] is True


def test_branding_write_permission_and_schema_boundary(client: TestClient) -> None:
    _login(client, "op", "op-pass")
    denied = client.put("/branding", json={"brand_names": {"en-US": "No"}})
    assert denied.status_code == 403
    assert (
        client.post(
            "/branding/assets/logo",
            files={"file": ("logo.png", PNG, "text/plain")},
        ).status_code
        == 403
    )
    client.post("/auth/logout")
    _login(client)
    assert client.put("/branding", json={"attribution": "Mine"}).status_code == 422
    whitespace = client.put(
        "/branding", json={"brand_names": {"en-US": "   "}}
    )
    assert whitespace.status_code == 422
    assert whitespace.json()["code"] == "BRANDING_INVALID"
    unknown_locale = client.put(
        "/branding", json={"brand_names": {"fr-FR": "Acme"}}
    )
    assert unknown_locale.status_code == 422
    assert unknown_locale.json()["code"] == "BRANDING_INVALID"
    incomplete = client.put("/branding", json={"primary_color": "#aabbcc"})
    assert incomplete.status_code == 422
    assert incomplete.json()["code"] == "BRANDING_INVALID"
    assert client.put("/branding", json={"primary_color": "#abcd"}).status_code == 422
    assert client.put("/branding", json={"primary_shades": ["#000000"]}).status_code == 422


def test_existing_custom_roles_do_not_gain_branding_write(client: TestClient) -> None:
    _login(client)
    created = client.post(
        "/roles",
        json={
            "key": "editor",
            "name": "Editor",
            "permissions": ["console:access", "dashboard:read", "settings:write"],
        },
    )
    assert created.status_code == 201
    permissions = created.json()["role"]["permissions"]
    assert "branding:write" not in permissions
    assert "branding:read" in ALL_PERMISSIONS


@pytest.mark.parametrize(
    ("kind", "content", "expected_type"),
    [
        ("logo", PNG, "image/png"),
        ("logo", JPEG, "image/jpeg"),
        ("logo", SVG, "image/svg+xml"),
        ("favicon", PNG, "image/png"),
        ("favicon", ICO, "image/vnd.microsoft.icon"),
    ],
)
def test_upload_accepts_detected_types_and_serves_immutable(
    client: TestClient,
    kind: str,
    content: bytes,
    expected_type: str,
) -> None:
    _login(client)
    uploaded = client.post(
        f"/branding/assets/{kind}",
        files={"file": ("asset.bin", content, "application/octet-stream")},
    )
    assert uploaded.status_code == 201
    body = uploaded.json()
    assert body["kind"] == kind
    assert body["content_type"] == expected_type
    assert body["byte_size"] == len(content)
    assert body["url"].startswith(f"/api/branding/assets/{kind}?v=")
    fetched = client.get(f"/branding/assets/{kind}")
    assert fetched.status_code == 200
    assert fetched.content == content
    assert fetched.headers["content-type"].startswith(expected_type)
    assert fetched.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert fetched.headers["x-content-type-options"] == "nosniff"
    if expected_type == "image/svg+xml":
        assert "default-src 'none'" in fetched.headers["content-security-policy"]
    not_modified = client.get(
        f"/branding/assets/{kind}",
        headers={"If-None-Match": fetched.headers["etag"]},
    )
    assert not_modified.status_code == 304


@pytest.mark.parametrize(
    ("kind", "content", "status", "code"),
    [
        ("favicon", JPEG, 415, "BRANDING_ASSET_TYPE_UNSUPPORTED"),
        ("favicon", SVG, 415, "BRANDING_ASSET_TYPE_UNSUPPORTED"),
        ("logo", ICO, 415, "BRANDING_ASSET_TYPE_UNSUPPORTED"),
        ("logo", b"not an image", 415, "BRANDING_ASSET_TYPE_UNSUPPORTED"),
        (
            "logo",
            b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
            b'<svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
            422,
            "BRANDING_ASSET_UNSAFE",
        ),
        (
            "logo",
            b'<?xml-stylesheet href="https://example.com/a.css"?>'
            b'<svg xmlns="http://www.w3.org/2000/svg"/>',
            422,
            "BRANDING_ASSET_UNSAFE",
        ),
        (
            "logo",
            b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>',
            422,
            "BRANDING_ASSET_UNSAFE",
        ),
        (
            "logo",
            b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
            422,
            "BRANDING_ASSET_UNSAFE",
        ),
        (
            "logo",
            b'<svg xmlns="http://www.w3.org/2000/svg">'
            b'<image href="https://example.com/a.png"/></svg>',
            422,
            "BRANDING_ASSET_UNSAFE",
        ),
        (
            "logo",
            b'<svg xmlns="http://www.w3.org/2000/svg">'
            b'<a href="javascript:alert(1)"/></svg>',
            422,
            "BRANDING_ASSET_UNSAFE",
        ),
        (
            "logo",
            b'<svg xmlns="http://www.w3.org/2000/svg">'
            b'<image href="data:image/svg+xml;utf8,'
            b'%3Csvg xmlns=%22http://www.w3.org/2000/svg%22%3E%3Cscript/%3E%3C/svg%3E"/>'
            b"</svg>",
            422,
            "BRANDING_ASSET_UNSAFE",
        ),
        (
            "logo",
            b'<svg xmlns="http://www.w3.org/2000/svg">'
            b'<rect id="r" width="1" height="1"/>'
            b'<animate href="#r" attributeName="opacity" values="0;1" dur="1s"/>'
            b"</svg>",
            422,
            "BRANDING_ASSET_UNSAFE",
        ),
        (
            "logo",
            b'<svg xmlns="http://www.w3.org/2000/svg">'
            b'<rect id="r" width="1" height="1"/>'
            b'<set href="#r" attributeName="opacity" to="0"/>'
            b"</svg>",
            422,
            "BRANDING_ASSET_UNSAFE",
        ),
        (
            "logo",
            b"<not-svg></not-svg>",
            422,
            "BRANDING_ASSET_INVALID",
        ),
    ],
)
def test_upload_rejects_wrong_kind_and_unsafe_content(
    client: TestClient, kind: str, content: bytes, status: int, code: str
) -> None:
    _login(client)
    response = client.post(
        f"/branding/assets/{kind}",
        files={"file": ("asset.bin", content, "image/png")},
    )
    assert response.status_code == status
    assert response.json()["code"] == code


def test_upload_rejects_extra_multipart_part(
    client: TestClient, stores: MemoryBrandingStore
) -> None:
    _login(client)
    response = client.post(
        "/branding/assets/logo",
        files={"file": ("logo.png", PNG, "image/png")},
        data={"note": "extra"},
    )
    assert_problem(response, status=422, code="REQUEST_INVALID")
    assert stores.get_asset("logo") is None


def test_upload_rejects_oversize_without_leaving_asset(client: TestClient) -> None:
    _login(client)
    response = client.post(
        "/branding/assets/logo",
        files={"file": ("large.png", PNG + b"x" * MAX_ASSET_BYTES, "image/png")},
    )
    assert response.status_code == 413
    assert client.get("/branding/assets/logo").status_code == 404


def test_asset_replace_delete_reset_cache_and_audit(
    client: TestClient, stores: MemoryBrandingStore
) -> None:
    _login(client)
    before_etag = client.get("/branding").headers["etag"]
    first = client.post(
        "/branding/assets/logo",
        files={"file": ("logo.png", PNG, "image/png")},
    )
    assert first.status_code == 201
    first_asset = stores.get_asset("logo")
    assert first_asset is not None
    second = client.post(
        "/branding/assets/logo",
        files={"file": ("logo.jpg", JPEG, "image/jpeg")},
    )
    assert second.status_code == 201
    second_asset = stores.get_asset("logo")
    assert second_asset is not None
    assert second_asset.id == first_asset.id
    assert second_asset.checksum != first_asset.checksum
    assert len(stores._assets) == 1  # noqa: SLF001
    after_etag = client.get("/branding").headers["etag"]
    assert after_etag != before_etag

    deleted = client.delete("/branding/assets/logo")
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert client.get("/branding/assets/logo").status_code == 404

    client.put("/branding", json={"brand_names": {"en-US": "Acme"}})
    reset = client.post("/branding/reset")
    assert reset.status_code == 204
    assert client.get("/branding").json() == DEFAULT_PUBLIC
    assert stores.get() is None
    assert stores.get_asset("logo") is None

    events, _ = get_audit_store().list_events(resource_type="site_branding")
    assert {event.action for event in events} >= {
        "branding.asset.replace",
        "branding.asset.delete",
        "branding.update",
        "branding.reset",
    }
    assert all("bytes" not in event.detail for event in events)


class _FailingBrandingStore:
    def get(self):
        raise RuntimeError("store down")

    def patch(self, values: dict[str, object], *, actor_user_id: str):
        raise RuntimeError("store down")

    def get_asset(self, kind: BrandingAssetKind):
        raise RuntimeError("store down")

    def replace_asset(
        self,
        *,
        kind: BrandingAssetKind,
        content_type: str,
        content: bytes,
        checksum: str,
    ):
        raise RuntimeError("store down")

    def delete_asset(self, kind: BrandingAssetKind):
        raise RuntimeError("store down")

    def reset(self) -> None:
        raise RuntimeError("store down")


def test_store_read_failure_is_branding_read_failed(client: TestClient) -> None:
    app.dependency_overrides[get_branding_store] = lambda: _FailingBrandingStore()
    public = client.get("/branding")
    assert_problem(public, status=503, code="BRANDING_READ_FAILED")
    asset = client.get("/branding/assets/logo")
    assert_problem(asset, status=503, code="BRANDING_READ_FAILED")


def test_store_write_failure_is_branding_write_failed(client: TestClient) -> None:
    _login(client)
    app.dependency_overrides[get_branding_store] = lambda: _FailingBrandingStore()
    updated = client.put("/branding", json={"brand_names": {"en-US": "Acme"}})
    assert_problem(updated, status=503, code="BRANDING_WRITE_FAILED")
    reset = client.post("/branding/reset")
    assert_problem(reset, status=503, code="BRANDING_WRITE_FAILED")


def test_packaged_seed_is_presented_without_writing_storage(
    client: TestClient,
    stores: MemoryBrandingStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REFRAQ_SKIP_SEED", "0")
    reset_branding_cache()
    presented = client.get("/branding").json()
    assert presented["logo_source"] == "seed"
    assert presented["favicon_source"] == "seed"
    assert presented["logo_url"]
    assert presented["favicon_url"]
    assert presented["show_logo"] is True
    assert stores.get_asset("logo") is None
    assert stores.get_asset("favicon") is None
    logo = client.get("/branding/assets/logo")
    favicon = client.get("/branding/assets/favicon")
    assert logo.status_code == 200
    assert favicon.status_code == 200
    assert logo.content == packaged_asset_bytes("logo")
    assert favicon.content == packaged_asset_bytes("favicon")
    assert presented["logo_url"].endswith(logo.headers["etag"].strip('"'))
    assert presented["favicon_url"].endswith(favicon.headers["etag"].strip('"'))

    _login(client)
    hidden = client.put("/branding", json={"show_logo": False})
    assert hidden.status_code == 200
    hidden_body = hidden.json()
    assert hidden_body["show_logo"] is False
    assert hidden_body["logo_url"] == presented["logo_url"]
    assert hidden_body["logo_source"] == "seed"
    still_served = client.get("/branding/assets/logo")
    assert still_served.status_code == 200
    assert still_served.content == packaged_asset_bytes("logo")

    uploaded = client.post(
        "/branding/assets/logo",
        files={"file": ("logo.png", PNG, "image/png")},
    )
    assert uploaded.status_code == 201
    user_logo = stores.get_asset("logo")
    assert user_logo is not None
    assert user_logo.origin == "user"
    assert stores.get_asset("favicon") is None
    public = client.get("/branding").json()
    assert public["logo_source"] == "user"
    assert public["favicon_source"] == "seed"


def test_upload_matching_seed_bytes_is_still_user(
    client: TestClient, stores: MemoryBrandingStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REFRAQ_SKIP_SEED", "0")
    reset_branding_cache()
    _login(client)
    content = packaged_asset_bytes("favicon")
    uploaded = client.post(
        "/branding/assets/favicon",
        files={"file": ("favicon.png", content, "image/png")},
    )
    assert uploaded.status_code == 201
    asset = stores.get_asset("favicon")
    assert asset is not None
    assert asset.origin == "user"
    assert asset.bytes == content
    assert client.get("/branding").json()["favicon_source"] == "user"


def test_delete_and_reset_restore_packaged_seed_without_writing_storage(
    client: TestClient,
    stores: MemoryBrandingStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REFRAQ_SKIP_SEED", "0")
    reset_branding_cache()
    _login(client)
    client.post(
        "/branding/assets/logo",
        files={"file": ("logo.png", PNG, "image/png")},
    )
    deleted = client.delete("/branding/assets/logo")
    assert deleted.status_code == 204
    assert stores.get_asset("logo") is None
    assert client.get("/branding").json()["logo_source"] == "seed"
    fetched = client.get("/branding/assets/logo")
    assert fetched.status_code == 200
    assert fetched.content == packaged_asset_bytes("logo")

    client.put(
        "/branding",
        json={"brand_names": {"en-US": "Acme"}, "show_logo": False},
    )
    reset = client.post("/branding/reset")
    assert reset.status_code == 204
    body = client.get("/branding").json()
    assert body["brand_names"] == {}
    assert body["show_logo"] is True
    assert body["logo_source"] == "seed"
    assert body["favicon_source"] == "seed"
    assert stores.get_asset("logo") is None
    assert stores.get_asset("favicon") is None
    assert client.get("/branding/assets/logo").content == packaged_asset_bytes("logo")
    assert client.get("/branding/assets/favicon").content == packaged_asset_bytes(
        "favicon"
    )


