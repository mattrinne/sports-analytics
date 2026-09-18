import pytest

from nfl_pipeline.datasets import REGISTRY
from nfl_pipeline.ingest import SeasonUnavailable, fetch


def test_out_of_range_season_raises_typed_exception(monkeypatch):
    def fake_loader(**kwargs):
        raise ValueError("Season must be between 2016 and 2025")

    import nflreadpy

    monkeypatch.setattr(nflreadpy, "load_participation", fake_loader)
    with pytest.raises(SeasonUnavailable):
        fetch(REGISTRY["participation"], 2099)


def test_other_value_errors_propagate(monkeypatch):
    def fake_loader(**kwargs):
        raise ValueError("something else")

    import nflreadpy

    monkeypatch.setattr(nflreadpy, "load_participation", fake_loader)
    with pytest.raises(ValueError, match="something else"):
        fetch(REGISTRY["participation"], 2024)
