from nfl_api.config import settings


def test_defaults(monkeypatch):
    for k in ("NFL_DATABASE_URL", "NFL_API_KEY", "NFL_API_CORS_ORIGINS"):
        monkeypatch.delenv(k, raising=False)
    s = settings()
    assert s.database_url.endswith("@localhost:5432/nfl")
    assert s.api_key is None
    assert s.cors_origins == ()
    assert (s.pool_min, s.pool_max) == (1, 10)


def test_empty_api_key_means_no_auth(monkeypatch):
    monkeypatch.setenv("NFL_API_KEY", "")  # compose passes ${NFL_API_KEY:-}
    assert settings().api_key is None
    monkeypatch.setenv("NFL_API_KEY", "s3cret")
    assert settings().api_key == "s3cret"


def test_pool_size_from_env(monkeypatch):
    monkeypatch.setenv("NFL_API_POOL_MIN", "2")
    monkeypatch.setenv("NFL_API_POOL_MAX", "20")
    s = settings()
    assert (s.pool_min, s.pool_max) == (2, 20)


def test_cors_origins_parsed(monkeypatch):
    monkeypatch.setenv("NFL_API_CORS_ORIGINS", " http://localhost:5173, ,https://hook.example ")
    assert settings().cors_origins == ("http://localhost:5173", "https://hook.example")
