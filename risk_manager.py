"""
Todo lo que decide "cuánto" y "si acaso no" arriesgar.
Esta pieza es la que hace que pasar a dinero real algún día no sea una locura.
"""
from dataclasses import dataclass
from datetime import date


@dataclass
class RiskState:
    day: date
    equity_at_day_start: float
    peak_equity: float


class RiskManager:
    def __init__(self, config):
        self.config = config
        self.state: RiskState | None = None

    def _ensure_day(self, equity: float):
        today = date.today()
        if self.state is None or self.state.day != today:
            peak = max(equity, self.state.peak_equity) if self.state else equity
            self.state = RiskState(day=today, equity_at_day_start=equity, peak_equity=peak)
        else:
            self.state.peak_equity = max(self.state.peak_equity, equity)

    def position_size(self, equity: float, entry_price: float, atr: float) -> float:
        """Tamaño en unidades del activo, según % de riesgo y distancia de stop (2x ATR)."""
        if atr <= 0 or entry_price <= 0:
            return 0.0
        risk_amount = equity * self.config.risk_per_trade_pct
        stop_distance = atr * 2
        qty = risk_amount / stop_distance
        # nunca comprometer más del tope de exposición por símbolo
        max_qty_by_exposure = (equity * self.config.max_exposure_per_symbol_pct) / entry_price
        return round(min(qty, max_qty_by_exposure), 6)

    def trading_allowed(self, equity: float) -> tuple[bool, str]:
        """Devuelve (permitido, motivo_si_no)."""
        self._ensure_day(equity)

        drawdown = (self.state.peak_equity - equity) / self.state.peak_equity if self.state.peak_equity else 0
        if drawdown >= self.config.max_drawdown_pct:
            return False, f"Drawdown máximo alcanzado ({drawdown:.1%}) — freno de emergencia activo"

        daily_loss = (self.state.equity_at_day_start - equity) / self.state.equity_at_day_start \
            if self.state.equity_at_day_start else 0
        if daily_loss >= self.config.max_daily_loss_pct:
            return False, f"Pérdida diaria máxima alcanzada ({daily_loss:.1%}) — sin nuevas entradas hoy"

        return True, ""
