import polars as pl
import pytest

from nfl_pipeline.db import pg_type, widened_type


@pytest.mark.parametrize(
    "dtype,expected",
    [
        (pl.Int32, "bigint"),
        (pl.Int64, "bigint"),
        (pl.UInt8, "bigint"),
        (pl.Float64, "double precision"),
        (pl.Float32, "double precision"),
        (pl.String, "text"),
        (pl.Null, "text"),
        (pl.Boolean, "boolean"),
        (pl.Date, "date"),
        (pl.Datetime("us", "UTC"), "timestamp with time zone"),
        (pl.Datetime("us"), "timestamp without time zone"),
    ],
)
def test_pg_type(dtype, expected):
    assert pg_type(dtype) == expected


def test_pg_type_rejects_nested():
    with pytest.raises(TypeError):
        pg_type(pl.List(pl.Int32))


@pytest.mark.parametrize(
    "existing,incoming,expected",
    [
        ("bigint", "bigint", None),
        ("bigint", "double precision", "double precision"),  # widen
        ("double precision", "bigint", None),  # narrower incoming, COPY parses ints as doubles
        ("bigint", "text", "text"),
        ("text", "bigint", None),
        ("date", "bigint", "text"),  # incompatible same-rank -> text
        ("boolean", "bigint", "bigint"),
    ],
)
def test_widened_type(existing, incoming, expected):
    assert widened_type(existing, incoming) == expected
