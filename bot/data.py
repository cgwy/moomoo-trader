"""Market data via futu-api QuoteContext (talks to local OpenD)."""

from __future__ import annotations

from datetime import date, timedelta

from futu import AuType, KLType, OpenQuoteContext, RET_OK


class QuoteClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 11111):
        self.ctx = OpenQuoteContext(host=host, port=port)

    def get_daily_klines(self, code: str, history_days: int = 120) -> list[dict]:
        """Daily bars, oldest -> newest: {"date", "open", "high", "low", "close", "volume"}."""
        end = date.today().strftime("%Y-%m-%d")
        start = (date.today() - timedelta(days=history_days)).strftime("%Y-%m-%d")
        ret, df = self.ctx.request_history_kline(
            code, start=start, end=end, ktype=KLType.K_DAY, autype=AuType.QFQ
        )
        if ret != RET_OK:
            raise RuntimeError(f"request_history_kline({code}) failed: {df}")
        bars = []
        for _, row in df.iterrows():
            bars.append({
                "date": str(row["time_key"])[:10],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
            })
        return bars

    def close(self):
        self.ctx.close()
