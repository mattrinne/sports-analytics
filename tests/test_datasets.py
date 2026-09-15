from nfl_pipeline.datasets import REGISTRY, Dataset, seasons_for


def test_registry_names_match_keys():
    for key, ds in REGISTRY.items():
        assert key == ds.name


def test_partitioned_datasets_have_min_season():
    for ds in REGISTRY.values():
        if ds.partitioned:
            assert ds.min_season is not None, ds.name


def test_seasons_for_clips_to_min_season():
    ds = Dataset(name="x", table="x", loader="load_x", description="", min_season=2002)
    assert seasons_for(ds, 1999, 2004) == [2002, 2003, 2004]
    assert seasons_for(ds, 2010, 2011) == [2010, 2011]
    assert seasons_for(ds, 2005, 2004) == []
