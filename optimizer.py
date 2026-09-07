"""
"La IA que aprende del mercado", en su versión honesta: walk-forward
optimization. Cada cierto tiempo, prueba una rejilla de parámetros sobre
los datos recientes y adopta la mejor combinación *si* mejora de forma
robusta (no solo en retorno bruto, también en drawdown).

No predice el futuro. Se readapta al régimen reciente con reglas claras
y un backtest vectorizado simple (no incluye slippage ni comisiones reales
— es una aproximación para comparar parámetros entre sí, no un backtest
de grado institucional).
"""
import itertools
from dataclasses import dataclass, asdict
import pandas as pd

from strategy import StrategyParams, add_indicators


@dataclass
class BacktestResult:
    params: StrategyParams
    total_return_pct: float
    max_drawdown_pct: float
    profit_factor: float
    num_trades: int


def backtest(df: pd.DataFrame, params: StrategyParams) -> BacktestResult:
    data = add_indicators(df, params).dropna(subset=["sma_slow", "rsi"]).copy()
    if len(data) < 10:
        return BacktestResult(params, 0.0, 0.0, 0.0, 0)

    golden = (data["sma_fast"] > data["sma_slow"]) & (data["sma_fast"].shift(1) <= data["sma_slow"].shift(1))
    death = (data["sma_fast"] < data["sma_slow"]) & (data["sma_fast"].shift(1) >= data["sma_slow"].shift(1))
    in_range = data["rsi"].between(params.rsi_low, params.rsi_high)

    position = 0
    entry_price = 0.0
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    gains, losses = [], []

    for i in range(len(data)):
        price = data["close"].iloc[i]
        if position == 0 and golden.iloc[i] and in_range.iloc[i]:
            position = 1
            entry_price = price
        elif position == 1 and (death.iloc[i] or data["rsi"].iloc[i] > params.rsi_high + 5):
            trade_return = (price - entry_price) / entry_price
            equity *= (1 + trade_return)
            (gains if trade_return > 0 else losses).append(trade_return)
            position = 0
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak)

    total_gain = sum(gains) or 0.0001
    total_loss = abs(sum(losses)) or 0.0001
    profit_factor = total_gain / total_loss

    return BacktestResult(
        params=params,
        total_return_pct=(equity - 1) * 100,
        max_drawdown_pct=max_dd * 100,
        profit_factor=round(profit_factor, 2),
        num_trades=len(gains) + len(losses),
    )


def optimize(df: pd.DataFrame, max_drawdown_allowed_pct: float) -> BacktestResult | None:
    """Rejilla pequeña a propósito: menos combinaciones = menos riesgo de sobreajuste."""
    grid = itertools.product(
        [10, 20, 30],       # sma_fast
        [40, 50, 60],       # sma_slow
        [(35, 65), (40, 70)],  # (rsi_low, rsi_high)
    )

    results = []
    for sma_fast, sma_slow, (rsi_low, rsi_high) in grid:
        if sma_fast >= sma_slow:
            continue
        params = StrategyParams(sma_fast=sma_fast, sma_slow=sma_slow, rsi_low=rsi_low, rsi_high=rsi_high)
        result = backtest(df, params)
        if result.num_trades >= 3 and result.max_drawdown_pct <= max_drawdown_allowed_pct * 100:
            results.append(result)

    if not results:
        return None

    return max(results, key=lambda r: r.profit_factor)
