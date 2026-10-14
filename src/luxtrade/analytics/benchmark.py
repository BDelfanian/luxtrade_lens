"""Benchmarking LU against other EU reporters: indexed growth and intra-EU share."""

import pandas as pd


def index_to_base(
    df: pd.DataFrame,
    base_period: int,
    group: str = "reporter",
    time: str = "period",
    value: str = "value",
) -> pd.Series:
    """Index each group's value to 100 in ``base_period`` (NaN if the base is missing)."""
    base = df[df[time] == base_period].set_index(group)[value]
    return 100.0 * df[value] / df[group].map(base)


def intra_share(df: pd.DataFrame) -> pd.DataFrame:
    """Intra-EU share (%) per reporter and period from rows split by trade_type."""
    wide = df.pivot_table(
        index=["reporter", "period"],
        columns="trade_type",
        values="value_eur",
        aggfunc="sum",
        fill_value=0,
    )
    total = wide.sum(axis=1)
    return (100.0 * wide.get("intra", 0) / total).rename("intra_share").reset_index()
