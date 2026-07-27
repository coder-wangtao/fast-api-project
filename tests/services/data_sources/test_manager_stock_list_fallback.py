"""
DataSourceManager.get_stock_list_with_fallback 单元测试

运行：
    python -m pytest tests/services/data_sources/test_manager_stock_list_fallback.py -v
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.services.data_sources.manager import DataSourceManager
from app.services.data_sources.tushare_adapter import TushareAdapter


def _df(source_tag: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["600000"],
            "name": [f"from_{source_tag}"],
            "ts_code": ["600000.SH"],
        }
    )


def _make_manager(adapter_specs: list[tuple[str, bool]]) -> DataSourceManager:
    """
    adapter_specs: [(name, available), ...]
    构造跳过真实初始化的 Manager，用 MagicMock 适配器替换。
    """
    with patch.object(TushareAdapter, "_initialize", lambda self: None), patch.object(
        DataSourceManager, "_load_priority_from_database", lambda self: None
    ):
        manager = DataSourceManager()

    mocks = []
    for name, available in adapter_specs:
        m = MagicMock()
        m.name = name
        m.priority = {"tushare": 3, "akshare": 2, "baostock": 1}.get(name, 0)
        m.is_available.return_value = available
        m.get_stock_list.return_value = None
        mocks.append(m)

    manager.adapters = mocks
    return manager


class TestGetStockListWithFallback:
    def test_uses_default_order_when_no_preferred(self):
        manager = _make_manager(
            [("tushare", True), ("akshare", True), ("baostock", True)]
        )
        # tushare 失败，akshare 成功
        manager.adapters[0].get_stock_list.return_value = None
        manager.adapters[1].get_stock_list.return_value = _df("akshare")

        df, source = manager.get_stock_list_with_fallback()

        assert source == "akshare"
        assert df is not None
        assert df.iloc[0]["name"] == "from_akshare"
        manager.adapters[0].get_stock_list.assert_called_once()
        manager.adapters[1].get_stock_list.assert_called_once()
        manager.adapters[2].get_stock_list.assert_not_called()

    def test_preferred_sources_reorder(self):
        """preferred=['akshare','baostock'] → 先 akshare，再 baostock，再 tushare"""
        manager = _make_manager(
            [("tushare", True), ("akshare", True), ("baostock", True)]
        )
        manager.adapters[0].get_stock_list.return_value = _df("tushare")
        manager.adapters[1].get_stock_list.return_value = _df("akshare")
        manager.adapters[2].get_stock_list.return_value = _df("baostock")

        df, source = manager.get_stock_list_with_fallback(
            preferred_sources=["akshare", "baostock"]
        )

        assert source == "akshare"
        assert df.iloc[0]["name"] == "from_akshare"
        # akshare 先被调用；tushare 不应被调用（已成功）
        manager.adapters[1].get_stock_list.assert_called_once()
        manager.adapters[0].get_stock_list.assert_not_called()
        manager.adapters[2].get_stock_list.assert_not_called()

    def test_fallback_to_next_preferred_when_first_fails(self):
        manager = _make_manager(
            [("tushare", True), ("akshare", True), ("baostock", True)]
        )
        manager.adapters[1].get_stock_list.return_value = None  # akshare 失败
        manager.adapters[1].get_stock_list.side_effect = None
        manager.adapters[2].get_stock_list.return_value = _df("baostock")

        df, source = manager.get_stock_list_with_fallback(
            preferred_sources=["akshare", "baostock"]
        )

        assert source == "baostock"
        assert df.iloc[0]["name"] == "from_baostock"

    def test_fallback_to_others_after_preferred_fail(self):
        """偏好源都失败时，继续试 others（tushare）"""
        manager = _make_manager(
            [("tushare", True), ("akshare", True), ("baostock", True)]
        )
        manager.adapters[1].get_stock_list.return_value = pd.DataFrame()  # empty
        manager.adapters[2].get_stock_list.return_value = None
        manager.adapters[0].get_stock_list.return_value = _df("tushare")

        df, source = manager.get_stock_list_with_fallback(
            preferred_sources=["akshare", "baostock"]
        )

        assert source == "tushare"
        assert df.iloc[0]["name"] == "from_tushare"

    def test_skips_unavailable_adapters(self):
        manager = _make_manager(
            [("tushare", False), ("akshare", True), ("baostock", True)]
        )
        manager.adapters[1].get_stock_list.return_value = _df("akshare")

        df, source = manager.get_stock_list_with_fallback()

        assert source == "akshare"
        manager.adapters[0].get_stock_list.assert_not_called()

    def test_exception_continues_to_next(self):
        manager = _make_manager(
            [("tushare", True), ("akshare", True), ("baostock", False)]
        )
        manager.adapters[0].get_stock_list.side_effect = RuntimeError("api down")
        manager.adapters[1].get_stock_list.return_value = _df("akshare")

        df, source = manager.get_stock_list_with_fallback()

        assert source == "akshare"
        assert df is not None

    def test_all_fail_returns_none(self):
        manager = _make_manager(
            [("tushare", True), ("akshare", True), ("baostock", True)]
        )
        for a in manager.adapters:
            a.get_stock_list.return_value = None

        df, source = manager.get_stock_list_with_fallback()

        assert df is None
        assert source is None

    def test_empty_dataframe_treated_as_failure(self):
        manager = _make_manager([("tushare", True), ("akshare", True)])
        manager.adapters[0].get_stock_list.return_value = pd.DataFrame()
        manager.adapters[1].get_stock_list.return_value = _df("akshare")

        df, source = manager.get_stock_list_with_fallback()

        assert source == "akshare"
        assert not df.empty
