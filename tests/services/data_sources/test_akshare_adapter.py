"""
AKShareAdapter 单元测试（mock akshare，不联网）

运行：
    python -m pytest tests/services/data_sources/test_akshare_adapter.py -v
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from app.services.data_sources.akshare_adapter import AKShareAdapter


@pytest.fixture
def adapter() -> AKShareAdapter:
    return AKShareAdapter()


class TestBasics:
    def test_name(self, adapter: AKShareAdapter):
        assert adapter.name == "akshare"

    def test_default_priority(self, adapter: AKShareAdapter):
        assert adapter._get_default_priority() == 2
        assert adapter.priority == 2

    def test_is_available_when_installed(self, adapter: AKShareAdapter):
        assert adapter.is_available() is True

    def test_is_available_when_missing(self, adapter: AKShareAdapter):
        with patch.dict("sys.modules", {"akshare": None}):
            # 强制 import 失败
            with patch("builtins.__import__", side_effect=ImportError("no akshare")):
                assert adapter.is_available() is False

    def test_safe_float(self, adapter: AKShareAdapter):
        assert adapter._safe_float("12.5") == 12.5
        assert adapter._safe_float("") is None
        assert adapter._safe_float(None) is None
        assert adapter._safe_float("None") is None
        assert adapter._safe_float("abc") is None

    def test_find_latest_trade_date(self, adapter: AKShareAdapter):
        expected = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        assert adapter.find_latest_trade_date() == expected


class TestGetStockList:
    def test_returns_none_when_unavailable(self, adapter: AKShareAdapter):
        with patch.object(adapter, "is_available", return_value=False):
            assert adapter.get_stock_list() is None

    def test_normalizes_columns_and_ts_code(self, adapter: AKShareAdapter):
        raw = pd.DataFrame(
            {
                "code": ["600000", "000001", "300750", "688001", "830799"],
                "name": ["浦发银行", "平安银行", "宁德时代", "华兴源创", "测试北交"],
            }
        )
        import akshare as ak

        with patch.object(adapter, "is_available", return_value=True), patch.object(
            ak, "stock_info_a_code_name", return_value=raw
        ):
            df = adapter.get_stock_list()

        assert df is not None
        assert "symbol" in df.columns
        assert "ts_code" in df.columns
        assert "market" in df.columns

        by_symbol = df.set_index("symbol")
        assert by_symbol.loc["600000", "ts_code"] == "600000.SH"
        assert by_symbol.loc["000001", "ts_code"] == "000001.SZ"
        assert by_symbol.loc["300750", "ts_code"] == "300750.SZ"
        assert by_symbol.loc["688001", "ts_code"] == "688001.SH"
        assert by_symbol.loc["830799", "ts_code"] == "830799.BJ"
        assert by_symbol.loc["600000", "market"] == "主板"
        assert by_symbol.loc["300750", "market"] == "创业板"
        assert by_symbol.loc["688001", "market"] == "科创板"

    def test_empty_dataframe_returns_none(self, adapter: AKShareAdapter):
        import akshare as ak

        with patch.object(adapter, "is_available", return_value=True), patch.object(
            ak, "stock_info_a_code_name", return_value=pd.DataFrame()
        ):
            assert adapter.get_stock_list() is None


class TestGetDailyBasic:
    def test_limits_to_10_stocks_and_converts_mv(self, adapter: AKShareAdapter):
        stock_df = pd.DataFrame(
            {
                "symbol": [f"{i:06d}" for i in range(1, 16)],
                "name": [f"股票{i}" for i in range(1, 16)],
                "ts_code": [f"{i:06d}.SZ" for i in range(1, 16)],
            }
        )

        info_df = pd.DataFrame(
            {
                "item": ["最新", "总市值"],
                "value": ["10.5", "100000"],  # 总市值：万元 → 应转成 10 亿元
            }
        )

        import akshare as ak

        with patch.object(adapter, "is_available", return_value=True), patch.object(
            adapter, "get_stock_list", return_value=stock_df
        ), patch.object(ak, "stock_individual_info_em", return_value=info_df):
            df = adapter.get_daily_basic("20260725")

        assert df is not None
        assert len(df) == 10  # max_stocks = 10
        assert df.iloc[0]["close"] == 10.5
        assert df.iloc[0]["total_mv"] == 10.0  # 100000 万 / 10000 = 10 亿
        assert df.iloc[0]["trade_date"] == "20260725"


class TestGetRealtimeQuotes:
    def test_eastmoney_snapshot_normalizes_code(self, adapter: AKShareAdapter):
        raw = pd.DataFrame(
            {
                "代码": ["sh600000", "sz000001", "300750"],
                "最新价": [10.1, 11.2, 200.5],
                "涨跌幅": [1.2, -0.5, 3.3],
                "成交额": [1e8, 2e8, 3e8],
                "成交量": [1000, 2000, 3000],
                "今开": [10.0, 11.0, 198.0],
                "最高": [10.5, 11.5, 205.0],
                "最低": [9.8, 10.8, 197.0],
                "昨收": [10.0, 11.3, 194.0],
            }
        )
        import akshare as ak

        with patch.object(adapter, "is_available", return_value=True), patch.object(
            ak, "stock_zh_a_spot_em", return_value=raw
        ):
            result = adapter.get_realtime_quotes(source="eastmoney")

        assert result is not None
        assert "600000" in result
        assert "000001" in result
        assert "300750" in result
        assert result["600000"]["close"] == 10.1
        assert result["000001"]["pct_chg"] == -0.5
        assert result["300750"]["volume"] == 3000

    def test_empty_snapshot_returns_none(self, adapter: AKShareAdapter):
        import akshare as ak

        with patch.object(adapter, "is_available", return_value=True), patch.object(
            ak, "stock_zh_a_spot_em", return_value=pd.DataFrame()
        ):
            assert adapter.get_realtime_quotes() is None


class TestGetKline:
    def test_daily_kline(self, adapter: AKShareAdapter):
        raw = pd.DataFrame(
            {
                "日期": ["2026-07-24", "2026-07-25"],
                "开盘": [10.0, 10.2],
                "最高": [10.5, 10.6],
                "最低": [9.9, 10.1],
                "收盘": [10.2, 10.4],
                "成交量": [100, 200],
                "成交额": [1000, 2000],
            }
        )
        import akshare as ak

        with patch.object(adapter, "is_available", return_value=True), patch.object(
            ak, "stock_zh_a_hist", return_value=raw
        ):
            items = adapter.get_kline("600000", period="day", limit=120)

        assert items is not None
        assert len(items) == 2
        assert items[-1]["close"] == 10.4
        assert items[-1]["time"] == "2026-07-25"


class TestGetNews:
    def test_news_and_announcements(self, adapter: AKShareAdapter):
        news_df = pd.DataFrame(
            {
                "新闻标题": ["标题A"],
                "文章来源": ["来源A"],
                "发布时间": ["2026-07-25"],
                "新闻链接": ["http://a"],
            }
        )
        ann_df = pd.DataFrame(
            {
                "公告标题": ["公告B"],
                "公告时间": ["2026-07-24"],
                "公告链接": ["http://b"],
            }
        )
        import akshare as ak

        with patch.object(adapter, "is_available", return_value=True), patch.object(
            ak, "stock_news_em", return_value=news_df
        ), patch.object(
            ak, "stock_announcement_em", return_value=ann_df, create=True
        ):
            items = adapter.get_news("600000", limit=50)

        assert items is not None
        assert len(items) == 2
        assert items[0]["type"] == "news"
        assert items[1]["type"] == "announcement"
