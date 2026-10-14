import pytest

from luxtrade.agents.sql_guard import SQLRejectedError, check_sql


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE trade",
        "SELECT 1 FROM v_lu_trade; SELECT 2 FROM v_lu_trade",
        "SELECT * FROM trade",
        "SELECT * FROM read_parquet('data/processed/trade.parquet')",
        "ATTACH 'x.db' AS x",
        "COPY (SELECT 1) TO 'out.csv'",
        "INSTALL httpfs",
        "PRAGMA database_list",
        "SET enable_external_access = true",
        "SELECT * FROM main.trade",
        "SELECT * FROM v_lu_trade WHERE partner IN (SELECT partner FROM partners)",
        "INSERT INTO v_lu_trade VALUES (1)",
    ],
)
def test_rejects_unsafe_sql(sql):
    with pytest.raises(SQLRejectedError):
        check_sql(sql)


def test_accepts_select_on_views_and_ctes():
    out = check_sql("WITH t AS (SELECT * FROM v_lu_trade_hs2) SELECT hs2 FROM t")
    assert "LIMIT 10000" in out


def test_caps_large_limits():
    assert "LIMIT 10000" in check_sql("SELECT * FROM v_lu_trade LIMIT 999999")
    assert "LIMIT 5" in check_sql("SELECT * FROM v_lu_trade LIMIT 5")


def test_accepts_slashes_in_benign_string_literals():
    sql = "SELECT 'kg/m' AS unit, 'apples and/or oranges' AS desc FROM v_lu_trade"
    checked = check_sql(sql)
    assert "kg/m" in checked

