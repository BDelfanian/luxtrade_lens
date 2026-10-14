"""Rankings and composition: Top-N + "Other" + "Confidential/undisclosed", shares that add up."""

import pandas as pd

UNDISCLOSED = "UNDISCLOSED"
OTHER = "OTHER"
CONFIDENTIAL = "CONFIDENTIAL"


def is_hidden_key(key: str) -> bool:
    """Keys that are kept in totals but never ranked: masked products, chapter 99, Q* partners."""
    return key == UNDISCLOSED or "X" in key or key == "99"


def top_n_with_other(
    df: pd.DataFrame, n: int, key: str = "key", value: str = "value"
) -> pd.DataFrame:
    """Keep the ``n`` largest visible keys; pool the rest as OTHER, hidden keys as CONFIDENTIAL.

    The output always sums to the input total, and ``share`` is a percentage of that total.
    Columns: key, value, share, rank (None for pooled rows), kind (item/other/confidential).
    """
    df = df.groupby(key, as_index=False)[value].sum()
    total = df[value].sum()
    hidden_mask = df[key].map(is_hidden_key)
    visible = df[~hidden_mask].sort_values(value, ascending=False)
    top = visible.head(n).assign(kind="item")
    top["rank"] = range(1, len(top) + 1)
    rows = [top]
    rest = visible.iloc[n:][value].sum()
    if rest > 0:
        rows.append(pd.DataFrame({key: [OTHER], value: [rest], "kind": ["other"], "rank": [None]}))
    hidden = df[hidden_mask][value].sum()
    if hidden > 0:
        label = UNDISCLOSED if (df[hidden_mask][key] == UNDISCLOSED).all() else CONFIDENTIAL
        rows.append(
            pd.DataFrame({key: [label], value: [hidden], "kind": ["confidential"], "rank": [None]})
        )
    out = pd.concat(rows, ignore_index=True)
    out["share"] = 100.0 * out[value] / total if total else 0.0
    return out[[key, value, "share", "rank", "kind"]]


def rank_by_flow(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Apply ``top_n_with_other`` per flow; with both flows also rank total trade."""
    parts = [top_n_with_other(g, n).assign(flow=flow) for flow, g in df.groupby("flow")]
    flows = set(df["flow"])
    if {"export", "import"} <= flows:
        parts.append(top_n_with_other(df, n).assign(flow="total"))
    return pd.concat(parts, ignore_index=True)


def concentration(shares: pd.Series, k: int) -> float:
    """Share (%) held by the ``k`` largest items."""
    return float(shares.sort_values(ascending=False).head(k).sum())


def hhi(shares_pct: pd.Series) -> float:
    """Herfindahl–Hirschman index on percentage shares (0–10 000)."""
    return float((shares_pct**2).sum())
