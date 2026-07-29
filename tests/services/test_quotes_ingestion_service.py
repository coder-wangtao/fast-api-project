"""
QuotesIngestionService 单元测试（mock Mongo / 数据源，不联网）

运行：
    python -m pytest tests/services/test_quotes_ingestion_service.py -v
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.services.quotes_ingestion_service import QuotesIngestionService


SH = ZoneInfo("Asia/Shanghai")


@pytest.fixture
def service() -> QuotesIngestionService:
    return QuotesIngestionService(collection_name="market_quotes")


class TestNormalizeStockCode:
    def test_plain_and_prefixed(self, service: QuotesIngestionService):
        assert service._normalize_stock_code("600000") == "600000"
        assert service._normalize_stock_code("sz000001") == "000001"
        assert service._normalize_stock_code("sh600036") == "600036"
        assert service._normalize_stock_code("1") == "000001"
        assert service._normalize_stock_code("") == ""
        assert service._normalize_stock_code("abc") == ""


class TestIsTradingTime:
    def test_weekday_morning(self, service: QuotesIngestionService):
        # 2026-07-27 是周一
        now = datetime(2026, 7, 27, 10, 0, tzinfo=SH)
        assert service._is_trading_time(now) is True

    def test_weekday_lunch_break(self, service: QuotesIngestionService):
        now = datetime(2026, 7, 27, 12, 0, tzinfo=SH)
        assert service._is_trading_time(now) is False

    def test_weekday_afternoon_and_buffer(self, service: QuotesIngestionService):
        assert service._is_trading_time(datetime(2026, 7, 27, 14, 0, tzinfo=SH)) is True
        assert service._is_trading_time(datetime(2026, 7, 27, 15, 15, tzinfo=SH)) is True
        assert service._is_trading_time(datetime(2026, 7, 27, 15, 31, tzinfo=SH)) is False

    def test_weekend(self, service: QuotesIngestionService):
        # 2026-07-25 是周六
        now = datetime(2026, 7, 25, 10, 0, tzinfo=SH)
        assert service._is_trading_time(now) is False


class TestTushareRateLimit:
    def test_premium_always_allowed(self, service: QuotesIngestionService):
        service._tushare_has_premium = True
        assert service._can_call_tushare() is True

    def test_free_user_hourly_limit(self, service: QuotesIngestionService):
        service._tushare_has_premium = False
        service._tushare_hourly_limit = 2
        now = datetime.now(SH)
        service._tushare_call_times.append(now - timedelta(minutes=10))
        service._tushare_call_times.append(now - timedelta(minutes=5))
        assert service._can_call_tushare() is False

    def test_old_calls_are_pruned(self, service: QuotesIngestionService):
        service._tushare_has_premium = False
        service._tushare_hourly_limit = 2
        service._tushare_call_times.append(datetime.now(SH) - timedelta(hours=2))
        assert service._can_call_tushare() is True

    def test_record_call(self, service: QuotesIngestionService):
        assert len(service._tushare_call_times) == 0
        service._record_tushare_call()
        assert len(service._tushare_call_times) == 1


class TestRotation:
    def test_rotation_cycle(self, service: QuotesIngestionService):
        with patch("app.services.quotes_ingestion_service.settings") as mock_settings:
            mock_settings.QUOTES_ROTATION_ENABLED = True
            results = [service._get_next_source() for _ in range(3)]

        assert results == [
            ("tushare", None),
            ("akshare", "eastmoney"),
            ("akshare", "sina"),
        ]
        # 第四次又回到 tushare
        with patch("app.services.quotes_ingestion_service.settings") as mock_settings:
            mock_settings.QUOTES_ROTATION_ENABLED = True
            assert service._get_next_source() == ("tushare", None)

    def test_rotation_disabled_defaults_to_tushare(self, service: QuotesIngestionService):
        with patch("app.services.quotes_ingestion_service.settings") as mock_settings:
            mock_settings.QUOTES_ROTATION_ENABLED = False
            assert service._get_next_source() == ("tushare", None)


class TestGetSyncStatus:
    @pytest.mark.asyncio
    async def test_never_synced(self, service: QuotesIngestionService):
        mock_coll = AsyncMock()
        mock_coll.find_one = AsyncMock(return_value=None)
        mock_db = MagicMock()
        mock_db.__getitem__.return_value = mock_coll

        with patch(
            "app.services.quotes_ingestion_service.get_mongo_db", return_value=mock_db
        ), patch(
            "app.services.quotes_ingestion_service.settings"
        ) as mock_settings:
            mock_settings.QUOTES_INGEST_INTERVAL_SECONDS = 360
            status = await service.get_sync_status()

        assert status["last_sync_time"] is None
        assert status["error_message"] == "尚未执行过同步"
        assert status["interval_minutes"] == 6

    @pytest.mark.asyncio
    async def test_existing_doc(self, service: QuotesIngestionService):
        ts = datetime(2026, 7, 28, 7, 0, tzinfo=ZoneInfo("UTC"))  # UTC 15:00 CST
        mock_coll = AsyncMock()
        mock_coll.find_one = AsyncMock(
            return_value={
                "_id": "x",
                "job": "quotes_ingestion",
                "last_sync_time": ts,
                "last_sync_time_iso": ts.isoformat(),
                "success": True,
                "data_source": "tushare",
                "records_count": 100,
                "interval_seconds": 360,
                "error_message": None,
            }
        )
        mock_db = MagicMock()
        mock_db.__getitem__.return_value = mock_coll

        with patch(
            "app.services.quotes_ingestion_service.get_mongo_db", return_value=mock_db
        ):
            status = await service.get_sync_status()

        assert status["success"] is True
        assert status["data_source"] == "tushare"
        assert status["records_count"] == 100
        assert "job" not in status
        assert "_id" not in status
        assert status["last_sync_time"] == "2026-07-28 15:00:00"


class TestBulkUpsert:
    @pytest.mark.asyncio
    async def test_normalizes_code_and_writes(self, service: QuotesIngestionService):
        mock_result = MagicMock()
        mock_result.matched_count = 0
        mock_result.upserted_ids = {"0": "id1"}
        mock_result.modified_count = 0

        mock_coll = AsyncMock()
        mock_coll.bulk_write = AsyncMock(return_value=mock_result)
        mock_db = MagicMock()
        mock_db.__getitem__.return_value = mock_coll

        quotes = {
            "sz000001": {
                "close": 11.0,
                "pct_chg": 1.0,
                "amount": 1e8,
                "volume": 1000,
                "open": 10.5,
                "high": 11.2,
                "low": 10.4,
                "pre_close": 10.9,
            },
            "": {"close": 1},  # 应跳过
        }

        with patch(
            "app.services.quotes_ingestion_service.get_mongo_db", return_value=mock_db
        ):
            await service._bulk_upsert(quotes, "20260728", "akshare_eastmoney")

        mock_coll.bulk_write.assert_awaited_once()
        ops = mock_coll.bulk_write.await_args.args[0]
        assert len(ops) == 1
        assert ops[0]._filter == {"code": "000001"}
        assert ops[0]._doc["$set"]["code"] == "000001"
        assert ops[0]._doc["$set"]["trade_date"] == "20260728"
        assert ops[0]._doc["$set"]["close"] == 11.0

    @pytest.mark.asyncio
    async def test_empty_quotes_skips_write(self, service: QuotesIngestionService):
        mock_coll = AsyncMock()
        mock_db = MagicMock()
        mock_db.__getitem__.return_value = mock_coll

        with patch(
            "app.services.quotes_ingestion_service.get_mongo_db", return_value=mock_db
        ):
            await service._bulk_upsert({}, "20260728", "tushare")

        mock_coll.bulk_write.assert_not_called()


class TestFetchQuotesFromSource:
    def test_tushare_blocked_by_rate_limit(self, service: QuotesIngestionService):
        with patch.object(service, "_can_call_tushare", return_value=False):
            quotes, source = service._fetch_quotes_from_source("tushare")
        assert quotes is None
        assert source is None

    def test_akshare_success(self, service: QuotesIngestionService):
        fake_quotes = {"000001": {"close": 11.0}}
        fake_adapter = MagicMock()
        fake_adapter.is_available.return_value = True
        fake_adapter.get_realtime_quotes.return_value = fake_quotes

        with patch(
            "app.services.data_sources.akshare_adapter.AKShareAdapter",
            return_value=fake_adapter,
        ):
            quotes, source = service._fetch_quotes_from_source("akshare", "eastmoney")

        assert quotes == fake_quotes
        assert source == "akshare_eastmoney"
        fake_adapter.get_realtime_quotes.assert_called_once_with(source="eastmoney")


class TestRunOnce:
    @pytest.mark.asyncio
    async def test_offhours_skips_when_backfill_disabled(self, service: QuotesIngestionService):
        with patch.object(service, "_is_trading_time", return_value=False), patch(
            "app.services.quotes_ingestion_service.settings"
        ) as mock_settings, patch.object(
            service, "backfill_last_close_snapshot_if_needed", new_callable=AsyncMock
        ) as mock_backfill:
            mock_settings.QUOTES_BACKFILL_ON_OFFHOURS = False
            await service.run_once()
            mock_backfill.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_offhours_triggers_backfill(self, service: QuotesIngestionService):
        with patch.object(service, "_is_trading_time", return_value=False), patch(
            "app.services.quotes_ingestion_service.settings"
        ) as mock_settings, patch.object(
            service, "backfill_last_close_snapshot_if_needed", new_callable=AsyncMock
        ) as mock_backfill:
            mock_settings.QUOTES_BACKFILL_ON_OFFHOURS = True
            await service.run_once()
            mock_backfill.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_trading_time_upserts_on_success(self, service: QuotesIngestionService):
        quotes = {"000001": {"close": 11.0, "pct_chg": 1.0}}

        with patch.object(service, "_is_trading_time", return_value=True), patch(
            "app.services.quotes_ingestion_service.settings"
        ) as mock_settings, patch.object(
            service, "_get_next_source", return_value=("akshare", "eastmoney")
        ), patch.object(
            service, "_fetch_quotes_from_source", return_value=(quotes, "akshare_eastmoney")
        ), patch.object(
            service, "_bulk_upsert", new_callable=AsyncMock
        ) as mock_upsert, patch.object(
            service, "_record_sync_status", new_callable=AsyncMock
        ) as mock_status, patch(
            "app.services.quotes_ingestion_service.DataSourceManager"
        ) as mock_manager_cls:
            mock_settings.QUOTES_AUTO_DETECT_TUSHARE_PERMISSION = False
            mock_manager_cls.return_value.find_latest_trade_date_with_fallback.return_value = (
                "20260728"
            )

            await service.run_once()

            mock_upsert.assert_awaited_once()
            assert mock_upsert.await_args.args[0] == quotes
            assert mock_upsert.await_args.args[1] == "20260728"
            mock_status.assert_awaited()
            assert mock_status.await_args.kwargs["success"] is True
            assert mock_status.await_args.kwargs["records_count"] == 1

    @pytest.mark.asyncio
    async def test_trading_time_records_failure_when_empty(self, service: QuotesIngestionService):
        with patch.object(service, "_is_trading_time", return_value=True), patch(
            "app.services.quotes_ingestion_service.settings"
        ) as mock_settings, patch.object(
            service, "_get_next_source", return_value=("tushare", None)
        ), patch.object(
            service, "_fetch_quotes_from_source", return_value=(None, "tushare")
        ), patch.object(
            service, "_bulk_upsert", new_callable=AsyncMock
        ) as mock_upsert, patch.object(
            service, "_record_sync_status", new_callable=AsyncMock
        ) as mock_status:
            mock_settings.QUOTES_AUTO_DETECT_TUSHARE_PERMISSION = False

            await service.run_once()

            mock_upsert.assert_not_awaited()
            mock_status.assert_awaited_once()
            assert mock_status.await_args.kwargs["success"] is False
