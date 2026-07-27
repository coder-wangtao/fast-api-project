"""
TushareAdapter 单元测试（mock provider/api，不联网）

运行：
    python -m pytest tests/services/data_sources/test_tushare_adapter.py -v
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.services.data_sources.tushare_adapter import TushareAdapter


@pytest.fixture
def adapter() -> TushareAdapter:
    """构造适配器，避免真实初始化 Tushare provider"""
    with patch.object(TushareAdapter, "_initialize", lambda self: None):
        a = TushareAdapter()
        a._provider = None
        return a


def _mock_provider(connected: bool = True, api: object | None = MagicMock()) -> MagicMock:
    provider = MagicMock()
    provider.connected = connected
    provider.api = api
    provider.token_source = "env"
    provider._normalize_symbol = MagicMock(side_effect=lambda c: f"{str(c).zfill(6)}.SH")
    return provider


class TestBasics:
    def test_name(self, adapter: TushareAdapter):
        assert adapter.name == "tushare"

    def test_default_priority(self, adapter: TushareAdapter):
        assert adapter._get_default_priority() == 3
        assert adapter.priority == 3

    def test_is_available_false_without_provider(self, adapter: TushareAdapter):
        adapter._provider = None
        assert adapter.is_available() is False

    def test_is_available_true_when_connected(self, adapter: TushareAdapter):
        adapter._provider = _mock_provider(connected=True)
        assert adapter.is_available() is True

    def test_is_available_tries_connect(self, adapter: TushareAdapter):
        provider = _mock_provider(connected=False)
        # connect_sync 后变成已连接
        def connect():
            provider.connected = True

        provider.connect_sync = MagicMock(side_effect=connect)
        adapter._provider = provider
        assert adapter.is_available() is True
        provider.connect_sync.assert_called_once()

    def test_get_token_source(self, adapter: TushareAdapter):
        adapter._provider = None
        assert adapter.get_token_source() is None
        adapter._provider = _mock_provider()
        assert adapter.get_token_source() == "env"


class TestGetStockList:
    def test_returns_none_when_unavailable(self, adapter: TushareAdapter):
        adapter._provider = None
        assert adapter.get_stock_list() is None

    def test_returns_dataframe(self, adapter: TushareAdapter):
        df = pd.DataFrame(
            {
                "ts_code": ["600000.SH", "000001.SZ"],
                "symbol": ["600000", "000001"],
                "name": ["浦发银行", "平安银行"],
            }
        )
        provider = _mock_provider()
        provider.get_stock_list_sync = MagicMock(return_value=df)
        adapter._provider = provider

        with patch.object(adapter, "is_available", return_value=True):
            result = adapter.get_stock_list()

        assert result is not None
        assert len(result) == 2
        provider.get_stock_list_sync.assert_called_once()


class TestGetDailyBasic:
    def test_returns_none_when_unavailable(self, adapter: TushareAdapter):
        adapter._provider = None
        assert adapter.get_daily_basic("20260725") is None

    def test_calls_api_and_returns_df(self, adapter: TushareAdapter):
        api = MagicMock()
        api.daily_basic.return_value = pd.DataFrame(
            {
                "ts_code": ["600000.SH"],
                "total_mv": [1000.0],
                "pe": [8.1],
                "pb": [0.9],
            }
        )
        adapter._provider = _mock_provider(api=api)

        with patch.object(adapter, "is_available", return_value=True):
            df = adapter.get_daily_basic("20260725")

        assert df is not None
        assert len(df) == 1
        api.daily_basic.assert_called_once()
        kwargs = api.daily_basic.call_args.kwargs
        assert kwargs["trade_date"] == "20260725"
        assert "total_mv" in kwargs["fields"]


class TestGetRealtimeQuotes:
    def test_returns_none_when_unavailable(self, adapter: TushareAdapter):
        adapter._provider = None
        assert adapter.get_realtime_quotes() is None

    def test_parses_rt_k_and_converts_volume(self, adapter: TushareAdapter):
        api = MagicMock()
        api.rt_k.return_value = pd.DataFrame(
            {
                "ts_code": ["600000.SH", "000001.SZ"],
                "close": [10.0, 11.0],
                "pre_close": [9.5, 11.0],
                "amount": [1e8, 2e8],
                "open": [9.8, 10.9],
                "high": [10.2, 11.2],
                "low": [9.7, 10.8],
                "vol": [100, 200],  # 手 -> 股 *100
            }
        )
        adapter._provider = _mock_provider(api=api)

        with patch.object(adapter, "is_available", return_value=True):
            result = adapter.get_realtime_quotes()

        assert result is not None
        assert "600000" in result
        assert "000001" in result
        assert result["600000"]["close"] == 10.0
        # (10/9.5 - 1) * 100 ≈ 5.263
        assert result["600000"]["pct_chg"] == pytest.approx((10.0 / 9.5 - 1) * 100)
        assert result["600000"]["volume"] == 10000
        assert result["000001"]["volume"] == 20000
        assert result["000001"]["pct_chg"] == 0.0

    def test_empty_rt_k_returns_none(self, adapter: TushareAdapter):
        api = MagicMock()
        api.rt_k.return_value = pd.DataFrame()
        adapter._provider = _mock_provider(api=api)

        with patch.object(adapter, "is_available", return_value=True):
            assert adapter.get_realtime_quotes() is None


class TestGetKline:
    def test_returns_none_when_unavailable(self, adapter: TushareAdapter):
        adapter._provider = None
        assert adapter.get_kline("600000") is None

    def test_daily_kline(self, adapter: TushareAdapter):
        provider = _mock_provider()
        adapter._provider = provider
        raw = pd.DataFrame(
            {
                "trade_date": ["20260724", "20260725"],
                "open": [10.0, 10.2],
                "high": [10.5, 10.6],
                "low": [9.9, 10.1],
                "close": [10.2, 10.4],
                "vol": [100, 200],
                "amount": [1000, 2000],
            }
        )

        fake_pro_bar = MagicMock(return_value=raw)
        fake_data_pro = MagicMock()
        fake_data_pro.pro_bar = fake_pro_bar
        fake_pro = MagicMock()
        fake_pro.data_pro = fake_data_pro
        fake_tushare = MagicMock()
        fake_tushare.pro = fake_pro

        with patch.object(adapter, "is_available", return_value=True), patch.dict(
            "sys.modules",
            {
                "tushare": fake_tushare,
                "tushare.pro": fake_pro,
                "tushare.pro.data_pro": fake_data_pro,
            },
        ):
            items = adapter.get_kline("600000", period="day", limit=120)

        assert items is not None
        assert len(items) == 2
        assert items[-1]["close"] == 10.4
        assert items[-1]["time"] == "20260725"
        assert items[-1]["volume"] == 200
        fake_pro_bar.assert_called_once()


class TestGetNews:
    def test_returns_none_when_unavailable(self, adapter: TushareAdapter):
        adapter._provider = None
        assert adapter.get_news("600000") is None

    def test_announcements_and_news(self, adapter: TushareAdapter):
        api = MagicMock()
        api.anns.return_value = pd.DataFrame(
            {
                "title": ["公告A"],
                "ann_date": ["20260725"],
                "url": ["http://a"],
            }
        )
        api.news.return_value = pd.DataFrame(
            {
                "title": ["新闻B"],
                "src": ["财联社"],
                "pub_time": ["2026-07-25 10:00:00"],
                "url": ["http://b"],
            }
        )
        adapter._provider = _mock_provider(api=api)

        with patch.object(adapter, "is_available", return_value=True):
            items = adapter.get_news("600000", days=2, limit=50)

        assert items is not None
        assert len(items) == 2
        assert items[0]["type"] == "announcement"
        assert items[1]["type"] == "news"
        assert items[1]["source"] == "财联社"


class TestFindLatestTradeDate:
    def test_returns_none_when_unavailable(self, adapter: TushareAdapter):
        adapter._provider = None
        assert adapter.find_latest_trade_date() is None

    def test_finds_first_non_empty_date(self, adapter: TushareAdapter):
        api = MagicMock()
        today = datetime.now()
        d0 = today.strftime("%Y%m%d")
        d1 = (today - timedelta(days=1)).strftime("%Y%m%d")

        def daily_basic(trade_date, fields):
            if trade_date == d0:
                return pd.DataFrame()  # 今天空
            if trade_date == d1:
                return pd.DataFrame({"ts_code": ["600000.SH"], "total_mv": [1.0]})
            return pd.DataFrame()

        api.daily_basic.side_effect = daily_basic
        adapter._provider = _mock_provider(api=api)

        with patch.object(adapter, "is_available", return_value=True):
            result = adapter.find_latest_trade_date()

        assert result == d1
