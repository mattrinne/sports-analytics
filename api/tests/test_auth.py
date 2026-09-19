from tests.conftest import FakeRepository, make_client


def test_no_key_configured_means_open():
    assert make_client(FakeRepository()).get("/teams").status_code == 200


def test_key_required_when_configured():
    c = make_client(FakeRepository(), api_key="s3cret")
    r = c.get("/teams")
    assert r.status_code == 401 and r.headers["WWW-Authenticate"] == "ApiKey"
    assert c.get("/teams", headers={"X-API-Key": "wrong"}).status_code == 401
    assert c.get("/teams", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert c.get("/games", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert c.get("/ops/runs").status_code == 401


def test_health_is_never_protected():
    assert make_client(FakeRepository(), api_key="s3cret").get("/health").status_code == 200


def test_openapi_declares_the_header():
    spec = make_client(FakeRepository(), api_key="s3cret").get("/openapi.json").json()
    assert spec["components"]["securitySchemes"]["APIKeyHeader"]["name"] == "X-API-Key"
