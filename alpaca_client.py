"""
Capa fina sobre alpaca-py. Todo lo que toca la API de Alpaca pasa por aquí,
así el resto del bot no depende directamente del SDK.
"""
import pandas as pd
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

from config import config


class AlpacaClient:
    def __init__(self):
        self.trading = TradingClient(
            config.alpaca_api_key,
            config.alpaca_secret_key,
            paper=config.alpaca_paper,
        )
        self.stock_data = StockHistoricalDataClient(config.alpaca_api_key, config.alpaca_secret_key)
        self.crypto_data = CryptoHistoricalDataClient(config.alpaca_api_key, config.alpaca_secret_key)

    def is_crypto(self, symbol: str) -> bool:
        return "/" in symbol

    def get_account(self):
        return self.trading.get_account()

    def get_equity(self) -> float:
        return float(self.get_account().equity)

    def get_open_position(self, symbol: str):
        try:
            return self.trading.get_open_position(symbol.replace("/", ""))
        except Exception:
            return None

    def get_bars(self, symbol: str, lookback_days: int = 200, timeframe=TimeFrame.Hour) -> pd.DataFrame:
        """Devuelve un DataFrame con columnas: open, high, low, close, volume."""
        start = pd.Timestamp.utcnow() - pd.Timedelta(days=lookback_days)

        if self.is_crypto(symbol):
            req = CryptoBarsRequest(symbol_or_symbols=symbol, timeframe=timeframe, start=start)
            bars = self.crypto_data.get_crypto_bars(req)
        else:
            req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=timeframe, start=start)
            bars = self.stock_data.get_stock_bars(req)

        df = bars.df
        if df.empty:
            return df
        # el df viene con multiindex (symbol, timestamp) cuando se pide un solo símbolo también
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol, level=0)
        return df[["open", "high", "low", "close", "volume"]]

    def is_market_open(self) -> bool:
        clock = self.trading.get_clock()
        return clock.is_open

    def submit_market_order(self, symbol: str, qty: float, side: str):
        """side: 'buy' o 'sell'. qty en unidades del activo (fraccional permitido)."""
        order = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.GTC if self.is_crypto(symbol) else TimeInForce.DAY,
        )
        return self.trading.submit_order(order)
