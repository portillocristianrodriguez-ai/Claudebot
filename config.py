"""
Configuración central del bot. Todo se lee de variables de entorno
(en local, desde un .env; en Railway, desde las Variables del servicio).
No metas claves reales en este archivo ni en el .env que subas a GitHub.
"""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv
from sp500 import SP500_TICKERS

load_dotenv()  # en Railway no hace nada (no hay .env), ahí las variables ya están inyectadas


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "si", "sí")


def _get_float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val else default


def _get_int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val else default


def _get_list(name: str, default: str) -> list[str]:
    val = os.getenv(name, default)
    return [s.strip() for s in val.split(",") if s.strip()]


@dataclass
class Config:
    # --- Alpaca ---
    alpaca_api_key: str = os.getenv("ALPACA_API_KEY", "")
    alpaca_secret_key: str = os.getenv("ALPACA_SECRET_KEY", "")
    alpaca_paper: bool = field(default_factory=lambda: _get_bool("ALPACA_PAPER", True))

    # --- Universo de activos ---
    # Por defecto: el S&P 500 completo en acciones (503 tickers), y en cripto
    # "ALL" es un centinela que main.py resuelve en arranque consultando a
    # Alpaca todos los pares que tenga disponibles ahora mismo. Puedes
    # sobreescribir cualquiera de las dos con una lista concreta por env var.
    symbols_stocks: list[str] = field(
        default_factory=lambda: _get_list("SYMBOLS_STOCKS", ",".join(SP500_TICKERS))
    )
    symbols_crypto: list[str] = field(default_factory=lambda: _get_list("SYMBOLS_CRYPTO", "ALL"))

    # --- Estrategia (valores por defecto; el optimizer los puede ir ajustando) ---
    sma_fast: int = field(default_factory=lambda: _get_int("SMA_FAST", 20))
    sma_slow: int = field(default_factory=lambda: _get_int("SMA_SLOW", 50))
    rsi_low: float = field(default_factory=lambda: _get_float("RSI_LOW", 40))
    rsi_high: float = field(default_factory=lambda: _get_float("RSI_HIGH", 70))

    # --- Riesgo ---
    risk_per_trade_pct: float = field(default_factory=lambda: _get_float("RISK_PER_TRADE_PCT", 0.01))
    max_daily_loss_pct: float = field(default_factory=lambda: _get_float("MAX_DAILY_LOSS_PCT", 0.03))
    max_drawdown_pct: float = field(default_factory=lambda: _get_float("MAX_DRAWDOWN_PCT", 0.10))
    max_exposure_per_symbol_pct: float = field(default_factory=lambda: _get_float("MAX_EXPOSURE_PER_SYMBOL_PCT", 0.25))

    # --- Ritmo ---
    loop_interval_minutes: int = field(default_factory=lambda: _get_int("LOOP_INTERVAL_MINUTES", 15))
    optimizer_interval_days: int = field(default_factory=lambda: _get_int("OPTIMIZER_INTERVAL_DAYS", 7))

    # --- Notificaciones ---
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # --- Dashboard web ---
    dashboard_user: str = os.getenv("DASHBOARD_USER", "admin")
    dashboard_password: str = os.getenv("DASHBOARD_PASSWORD", "")

    # --- Persistencia ---
    db_path: str = os.getenv("DB_PATH", "/data/trades.db")

    def validate(self) -> list[str]:
        """Devuelve una lista de problemas de configuración (vacía si todo bien)."""
        problems = []
        if not self.alpaca_api_key or not self.alpaca_secret_key:
            problems.append("Faltan ALPACA_API_KEY / ALPACA_SECRET_KEY")
        if not self.symbols_stocks and not self.symbols_crypto:
            problems.append("No hay símbolos configurados (SYMBOLS_STOCKS / SYMBOLS_CRYPTO)")
        return problems


config = Config()
