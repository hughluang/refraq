from fastapi.testclient import TestClient

from backend.main import app


def test_swagger_and_openapi_mounted_redoc_disabled() -> None:
    client = TestClient(app)

    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "swagger-ui" in docs.text.lower()
    assert "/openapi.json" in docs.text
    # Docs schema URL stays at web-origin /openapi.json (not /api/openapi.json).
    assert "/api/openapi.json" not in docs.text

    oauth_redirect = client.get("/docs/oauth2-redirect")
    assert oauth_redirect.status_code == 200

    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200
    body = openapi.json()
    assert body["info"]["title"] == "refraq Backend"
    assert "openapi" in body

    servers = body.get("servers") or []
    assert servers, "OpenAPI servers must be present for Try it out /api prefix"
    assert servers[0]["url"] == "/api"

    schemes = (body.get("components") or {}).get("securitySchemes") or {}
    assert "HTTPBearer" in schemes
    assert schemes["HTTPBearer"]["type"] == "http"
    assert schemes["HTTPBearer"]["scheme"] == "bearer"
    assert not any(
        isinstance(s, dict) and s.get("type") == "apiKey" and s.get("in") == "cookie"
        for s in schemes.values()
    )

    # Public ops stay unmarked; protected ops that use get_current_user carry Bearer.
    login = body["paths"]["/auth/login"]["post"]
    assert "security" not in login
    me = body["paths"]["/auth/me"]["get"]
    assert {"HTTPBearer": []} in (me.get("security") or [])

    health = client.get("/healthz")
    assert health.status_code == 200

    me_unauth = client.get("/auth/me")
    assert me_unauth.status_code == 401

    redoc = client.get("/redoc")
    assert redoc.status_code == 404
