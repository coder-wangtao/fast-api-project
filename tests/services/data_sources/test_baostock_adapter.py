"""
BaoStockAdapter 单元测试（mock baostock，不联网）

运行：
    python -m pytest tests/services/data_sources/test_baostock_adapter.py -v
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, List, Optional
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.services.data_sources.baostock_adapter import BaoStockAdapter


class FakeResult:
    """模拟 baostock 查询结果对象"""

    def __init__(
        self,
        rows: Optional[List[List[Any]]] = None,
        fields: Optional[List[str]] = None,
        error_code: str = "0",
        error_msg: str = "success",
    ):
        self.error_code = error_code
        self.error_msg = error_msg
        self.fields = fields or []
        self._rows = rows or []
        self._idx = -1

    def next(self) -> bool:
        self._idx += 1
        return self._idx < len(self._rows)

    def get_row_data(self) -> List[Any]:
        return self._rows[self._idx]


@pytest.fixture
def adapter() -> BaoStockAdapter:
    return BaoStockAdapter()


class TestBasics:
    def test_name(self, adapter: BaoStockAdapter):
        assert adapter.name == "baostock"

    def test_default_priority(self, adapter: BaoStockAdapter):
        assert adapter._get_default_priority() == 1
        assert adapter.priority == 1

    def test_is_available_when_installed(self, adapter: BaoStockAdapter):
        assert adapter.is_available() is True

    def test_is_available_when_missing(self, adapter: BaoStockAdapter):
        with patch("builtins.__import__", side_effect=ImportError("no baostock")):
            assert adapter.is_available() is False

    def test_safe_float(self, adapter: BaoStockAdapter):
        assert adapter._safe_float("12.5") == 12.5
        assert adapter._safe_float("") is None
        assert adapter._safe_float(None) is None
        assert adapter._safe_float("None") is None
        assert adapter._safe_float("abc") is None

    def test_find_latest_trade_date(self, adapter: BaoStockAdapter):
        expected = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        assert adapter.find_latest_trade_date() == expected

    def test_unsupported_apis_return_none(self, adapter: BaoStockAdapter):
        with patch.object(adapter, "is_available", return_value=True):
            assert adapter.get_realtime_quotes() is None
            assert adapter.get_kline("600000") is None
            assert adapter.get_news("600000") is None


class TestGetStockList:
    def test_returns_none_when_unavailable(self, adapter: BaoStockAdapter):
        with patch.object(adapter, "is_available", return_value=False):
            assert adapter.get_stock_list() is None

    def test_login_failed(self, adapter: BaoStockAdapter):
        import baostock as bs

        login_result = MagicMock(error_code="1", error_msg="login failed")
        with patch.object(adapter, "is_available", return_value=True), patch.object(
            bs, "login", return_value=login_result
        ):
            assert adapter.get_stock_list() is None

    def test_normalizes_stock_list_and_industry(self, adapter: BaoStockAdapter):
        import baostock as bs

        basic_rs = FakeResult(
            fields=["code", "code_name", "ipoDate", "outDate", "type", "status"],
            rows=[
                ["sh.600000", "浦发银行", "1999-11-10", "", "1", "1"],
                ["sz.000001", "平安银行", "1991-04-03", "", "1", "1"],
                ["sh.000001", "上证指数", "", "", "2", "1"],  # 非股票 type!=1，应过滤
            ],
        )
        industry_rs = FakeResult(
            fields=["updateDate", "code", "code_name", "industry", "industryClassification"],
            rows=[
                ["2026-07-01", "sh.600000", "浦发银行", "J66货币金融服务", "申万一级行业"],
                ["2026-07-01", "sz.000001", "平安银行", "J66货币金融服务", "申万一级行业"],
            ],
        )
        login_result = MagicMock(error_code="0", error_msg="success")

        with patch.object(adapter, "is_available", return_value=True), patch.object(
            bs, "login", return_value=login_result
        ), patch.object(bs, "logout", return_value=None), patch.object(
            bs, "query_stock_basic", return_value=basic_rs
        ), patch.object(bs, "query_stock_industry", return_value=industry_rs):
            df = adapter.get_stock_list()

        assert df is not None
        assert len(df) == 2
        assert list(df.columns) == [
            "symbol",
            "name",
            "ts_code",
            "area",
            "industry",
            "market",
            "list_date",
        ]

        by_symbol = df.set_index("symbol")
        assert by_symbol.loc["600000", "ts_code"] == "600000.SH"
        assert by_symbol.loc["000001", "ts_code"] == "000001.SZ"
        assert by_symbol.loc["600000", "name"] == "浦发银行"
        assert by_symbol.loc["600000", "industry"] == "货币金融服务"
        assert by_symbol.loc["600000", "market"] == "主板"


class TestGetDailyBasic:
    def test_returns_none_when_unavailable(self, adapter: BaoStockAdapter):
        with patch.object(adapter, "is_available", return_value=False):
            assert adapter.get_daily_basic("20260725") is None

    def test_fetches_valuation_with_max_stocks(self, adapter: BaoStockAdapter):
        import baostock as bs

        basic_rs = FakeResult(
            fields=["code", "code_name", "ipoDate", "outDate", "type", "status"],
            rows=[
                ["sh.600000", "浦发银行", "", "", "1", "1"],
                ["sz.000001", "平安银行", "", "", "1", "1"],
                ["sz.000002", "万科A", "", "", "1", "1"],
            ],
        )

        def valuation_side_effect(code, fields, start_date, end_date, frequency, adjustflag):
            assert start_date == "2026-07-25"
            assert end_date == "2026-07-25"
            if code == "sh.600000":
                return FakeResult(
                    rows=[["2026-07-25", "sh.600000", "10.5", "8.1", "0.9", "1.2", "3.4", "0"]]
                )
            if code == "sz.000001":
                return FakeResult(
                    rows=[["2026-07-25", "sz.000001", "11.2", "7.0", "0.8", "1.1", "2.2", "0"]]
                )
            return FakeResult(rows=[])

        login_result = MagicMock(error_code="0", error_msg="success")

        with patch.object(adapter, "is_available", return_value=True), patch.object(
            bs, "login", return_value=login_result
        ), patch.object(bs, "logout", return_value=None), patch.object(
            bs, "query_stock_basic", return_value=basic_rs
        ), patch.object(
            bs, "query_history_k_data_plus", side_effect=valuation_side_effect
        ):
            df = adapter.get_daily_basic("20260725", max_stocks=2)

        assert df is not None
        assert len(df) == 2
        first = df.set_index("ts_code").loc["600000.SH"]
        assert first["close"] == 10.5
        assert first["pe"] == 8.1
        assert first["pb"] == 0.9
        assert first["ps"] == 1.2
        assert first["pcf"] == 3.4
        assert first["total_mv"] is None
        assert first["turnover_rate"] is None
        assert first["trade_date"] == "20260725"
