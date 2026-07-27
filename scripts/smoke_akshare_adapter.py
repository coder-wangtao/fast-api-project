"""
AKShareAdapter 联网冒烟测试（真实调用 AKShare）

运行：
    python scripts/smoke_akshare_adapter.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.data_sources.akshare_adapter import AKShareAdapter


def main() -> int:
    adapter = AKShareAdapter()
    print(f"name={adapter.name}, priority={adapter.priority}")
    print(f"is_available={adapter.is_available()}")
    if not adapter.is_available():
        print("FAIL: akshare 未安装")
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
    print(stock_df.head(5)[["symbol", "name", "ts_code", "market"]].to_string(index=False))

    print("\n[3] get_realtime_quotes eastmoney (sample 3)")
    quotes = adapter.get_realtime_quotes(source="eastmoney")
    if not quotes:
        print("  WARN: 实时行情为空（非交易时段也可能正常）")
    else:
        for code in ("600000", "000001", "300750"):
            print(f"  {code}: {quotes.get(code)}")

    print("\n[4] get_kline 600000 day limit=3")
    kline = adapter.get_kline("600000", period="day", limit=3)
    print(f"  bars={len(kline) if kline else 0}")
    if kline:
        print(f"  last={kline[-1]}")

    print("\n[5] get_news 600000 limit=2")
    news = adapter.get_news("600000", limit=2, include_announcements=False)
    print(f"  items={len(news) if news else 0}")
    if news:
        print(f"  first={news[0]}")

    print("\nDONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
