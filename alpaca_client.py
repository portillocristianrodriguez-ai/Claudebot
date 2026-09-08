"""
Capa fina sobre alpaca-py. Todo lo que toca la API de Alpaca pasa por aquí,
así el resto del bot no depende directamente del SDK.

Pensado para trabajar con un universo grande de símbolos sin reventar el
rate limit (200 req/min en Alpaca): las velas se piden en LOTES
multi-símbolo, no una llamada por símbolo, y las posiciones se traen todas
de una vez. Cada lote tiene su propio timeout — si uno se cuelga, se
descarta ESE lote y se sigue con los demás, en vez de perder el ciclo entero.
"""
import signal
import pandas as pd
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetAssetsRequest
from alpaca.trading.enums import OrderSide, TimeInForce, AssetClass, AssetStatus
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

from config import config

CHUNK_SIZE = 20  # símbolos por llamada de velas — lotes pequeños para acotar el daño si uno se cuelga
CHUNK_TIMEOUT_SECONDS = 25


class ChunkTimeout(Exception):
    pass


def _alarm_handler(signum, frame):
    raise ChunkTimeout("lote tardó demasiado")


signal.signal(signal.SIGALRM, _alarm_handler)


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

    def get_all_positions_by_symbol(self) -> dict:
        """Una sola llamada; clave = symbol tal como lo devuelve Alpaca (cripto sin barra, p.ej. BTCUSD)."""
        positions = self.trading.get_all_positions()
        return {p.symbol: p for p in positions}

    def get_tradable_crypto_symbols(self) -> list[str]:
        """Todos los pares de cripto activos y operables en Alpaca ahora mismo."""
        req = GetAssetsRequest(asset_class=AssetClass.CRYPTO, status=AssetStatus.ACTIVE)
        assets = self.trading.get_all_assets(req)
        return [a.symbol for a in assets if a.tradable]

    def get_bars_batch(
        self, symbols: list[str], crypto: bool, lookback_days: int = 20, timeframe=TimeFrame.Hour
    ) -> dict[str, pd.DataFrame]:
        """Trae velas de muchos símbolos en lotes pequeños. Un lote colgado no tira los demás."""
        if not symbols:
            return {}
        start = pd.Timestamp.utcnow() - pd.Timedelta(days=lookback_days)
        result: dict[str, pd.DataFrame] = {}
        total_chunks = (len(symbols) + CHUNK_SIZE - 1) // CHUNK_SIZE

        for idx, i in enumerate(range(0, len(symbols), CHUNK_SIZE), start=1):
            chunk = symbols[i:i + CHUNK_SIZE]
            signal.alarm(CHUNK_TIMEOUT_SECONDS)
            try:
                if crypto:
                    req = CryptoBarsRequest(symbol_or_symbols=chunk, timeframe=timeframe, start=start)
                    bars = self.crypto_data.get_crypto_bars(req)
                else:
                    req = StockBarsRequest(symbol_or_symbols=chunk, timeframe=timeframe, start=start)
                    bars = self.stock_data.get_stock_bars(req)

                df = bars.df
                if not df.empty:
                    for sym in chunk:
                        try:
                            sym_df = df.xs(sym, level=0)
                        except KeyError:
                            continue
                        result[sym] = sym_df[["open", "high", "low", "close", "volume"]]
                print(f"  lote {idx}/{total_chunks} ({len(chunk)} símbolos): OK", flush=True)
            except Exception as e:
                print(f"  lote {idx}/{total_chunks} ({len(chunk)} símbolos, {chunk[0]}..{chunk[-1]}): "
                      f"FALLÓ, {type(e).__name__}: {e}", flush=True)
                continue
            finally:
                signal.alarm(0)

        return result

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
