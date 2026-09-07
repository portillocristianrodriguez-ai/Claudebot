"""
Estrategia V1: cruce de medias móviles con filtro de RSI.

Está separada en funciones puras (df -> df, df -> señal) para poder
reutilizarlas tanto en vivo como dentro del backtest del optimizer,
sin duplicar lógica.
"""
from dataclasses import dataclass
import pandas as pd
import numpy as np


@dataclass
class StrategyParams:
    sma_fast: int = 20
    sma_slow: int = 50
    rsi_period: int = 14
    rsi_low: float = 40.0
    rsi_high: float = 70.0


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def add_indicators(df: pd.DataFrame, params: StrategyParams) -> pd.DataFrame:
    out = df.copy()
    out["sma_fast"] = out["close"].rolling(params.sma_fast).mean()
    out["sma_slow"] = out["close"].rolling(params.sma_slow).mean()
    out["rsi"] = compute_rsi(out["close"], params.rsi_period)
    # ATR simple, para dimensionar la posición según volatilidad
    high_low = out["high"] - out["low"]
    high_close = (out["high"] - out["close"].shift()).abs()
    low_close = (out["low"] - out["close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    out["atr"] = true_range.rolling(14).mean()
    return out


def latest_signal(df_with_indicators: pd.DataFrame, params: StrategyParams) -> str:
    """Señal sobre la última vela cerrada: 'buy', 'sell' o 'hold'."""
    if len(df_with_indicators) < params.sma_slow + 1:
        return "hold"

    curr = df_with_indicators.iloc[-1]
    prev = df_with_indicators.iloc[-2]

    if pd.isna(curr["sma_slow"]) or pd.isna(prev["sma_slow"]):
        return "hold"

    golden_cross = prev["sma_fast"] <= prev["sma_slow"] and curr["sma_fast"] > curr["sma_slow"]
    death_cross = prev["sma_fast"] >= prev["sma_slow"] and curr["sma_fast"] < curr["sma_slow"]

    if golden_cross and params.rsi_low <= curr["rsi"] <= params.rsi_high:
        return "buy"
    if death_cross or curr["rsi"] > params.rsi_high + 5:
        return "sell"
    return "hold"
