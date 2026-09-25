"""Order execution via futu-api. Every order needs an explicit typed confirmation.

Safety model
------------
* Default trade_env is SIMULATE (paper trading).
* REAL orders are refused unless the caller passes allow_real=True, which
  main.py only sets after an extra typed confirmation at startup.
* Trade password is never stored in config; it comes from MOOMOO_TRADE_PWD.
"""

from __future__ import annotations

from futu import OpenSecTradeContext, OrderType, RET_OK, TrdSide


class OrderRefused(RuntimeError):
    pass


class Executor:
    def __init__(self, host: str = "127.0.0.1", port: int = 11111,
                 trade_env: str = "SIMULATE", password: str | None = None,
                 allow_real: bool = False):
        trade_env = trade_env.upper()
        if trade_env == "REAL" and not allow_real:
            raise OrderRefused(
                "Refusing to arm REAL trading without explicit allow_real=True "
                "(set after the extra typed confirmation)."
            )
        self.trade_env = trade_env
        self.allow_real = allow_real
        self.ctx = OpenSecTradeContext(host=host, port=port)
        if password:
            ret, msg = self.ctx.unlock_trade(password)
            if ret != RET_OK:
                raise RuntimeError(f"unlock_trade failed: {msg}")

    def place_limit_order(self, code: str, side: str, qty: int, price: float) -> dict:
        """side: "BUY" | "SELL". Returns the order result dict."""
        if self.trade_env == "REAL" and not self.allow_real:
            # Double-check at order time too — belt and suspenders.
            raise OrderRefused("REAL order blocked: allow_real not set")
        trd_side = TrdSide.BUY if side.upper() == "BUY" else TrdSide.SELL
        ret, data = self.ctx.place_order(
            price=round(float(price), 2),
            qty=int(qty),
            code=code,
            trd_side=trd_side,
            order_type=OrderType.NORMAL,
            trd_env=self.trade_env,
        )
        if ret != RET_OK:
            raise RuntimeError(f"place_order({code} {side} {qty}@{price}) failed: {data}")
        return {"code": code, "side": side.upper(), "qty": int(qty),
                "price": round(float(price), 2), "env": self.trade_env,
                "order": data.to_dict("records") if hasattr(data, "to_dict") else str(data)}

    def close(self):
        self.ctx.close()
