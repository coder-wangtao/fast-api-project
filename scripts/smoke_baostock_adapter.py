"""
BaoStockAdapter 联网冒烟测试（真实调用 BaoStock）

运行：
    python scripts/smoke_baostock_adapter.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.data_sources.baostock_adapter import BaoStockAdapter


def main() -> int:
    adapter = BaoStockAdapter()
    print(f"name={adapter.name}, priority={adapter.priority}")
    print(f"is_available={adapter.is_available()}")
    if not adapter.is_available():
        print("FAIL: baostock 未安装")
        return 1

    print("\n[1] find_latest_trade_date")
    trade_date = adapter.find_latest_trade_date()
    print(f"  trade_date={trade_date}")

    print("\n[2] get_stock_list (head 5)")
    stock_df = adapter.get_stock_list()
    if stock_df is None or stock_df.empty:
        print("  FAIL: 股票列表为空")
        return 1
    print(f"  total={len(stock_df)}")
    cols = [c for c in ["symbol", "name", "ts_code", "industry", "market"] if c in stock_df.columns]
    print(stock_df.head(5)[cols].to_string(index=False))

    print("\n[3] get_daily_basic (max_stocks=3)")
    daily = adapter.get_daily_basic(trade_date or "20260725", max_stocks=3)
    if daily is None or daily.empty:
        print("  WARN: 日度估值数据为空（周末/节假日可能正常）")
    else:
        print(daily.to_string(index=False))

    print("\n[4] unsupported APIs")
    print(f"  realtime={adapter.get_realtime_quotes()}")
    print(f"  kline={adapter.get_kline('600000')}")
    print(f"  news={adapter.get_news('600000')}")

    print("\nDONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
