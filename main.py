"""
Punto de entrada. Pensado para correr como worker de larga duración en
Railway (Procfile: `worker: python main.py`), no como servicio web.
"""
import time
import json
import signal
from datetime import datetime, timezone

from config import config
from alpaca_client import AlpacaClient
from strategy import StrategyParams, add_indicators, latest_signal
from risk_manager import RiskManager
from optimizer import optimize
from notifier import notify
import portfolio_state

STATE_FILE = "/data/strategy_state.json"


class BotTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise BotTimeout("tardó demasiado, probablemente colgado en una llamada de red")


signal.signal(signal.SIGALRM, _timeout_handler)


def resolve_universe(client: AlpacaClient) -> tuple[list[str], list[str]]:
    """SYMBOLS_STOCKS ya viene resuelto desde config (S&P 500 por defecto).
    SYMBOLS_CRYPTO=ALL se resuelve aquí consultando a Alpaca qué pares
    tiene disponibles ahora mismo."""
    stocks = config.symbols_stocks
    if config.symbols_crypto == ["ALL"]:
        signal.alarm(30)
        try:
            crypto = client.get_tradable_crypto_symbols()
        finally:
            signal.alarm(0)
    else:
        crypto = config.symbols_crypto
    return stocks, crypto


def load_params() -> StrategyParams:
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        return StrategyParams(**data["params"])
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return StrategyParams(
            sma_fast=config.sma_fast,
            sma_slow=config.sma_slow,
            rsi_low=config.rsi_low,
            rsi_high=config.rsi_high,
        )


def save_params(params: StrategyParams, last_optimized: str):
    with open(STATE_FILE, "w") as f:
        json.dump({"params": params.__dict__, "last_optimized": last_optimized}, f)


def get_last_optimized() -> datetime | None:
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        return datetime.fromisoformat(data["last_optimized"])
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return None


def run_cycle(client: AlpacaClient, risk: RiskManager, params: StrategyParams, stocks: list[str], crypto: list[str]):
    equity = client.get_equity()
    portfolio_state.record_equity(equity)

    allowed, reason = risk.trading_allowed(equity)
    if not allowed:
        notify(f"⏸️ Trading pausado: {reason}")
        return

    positions = client.get_all_positions_by_symbol()
    market_open = client.is_market_open()
    bars_by_symbol: dict = {}

    if stocks and market_open:
        signal.alarm(120)
        try:
            print(f"Consultando velas de {len(stocks)} acciones en lotes...", flush=True)
            stock_bars = client.get_bars_batch(stocks, crypto=False)
            bars_by_symbol.update(stock_bars)
            print(f"Recibidas velas de {len(stock_bars)}/{len(stocks)} acciones", flush=True)
        except Exception as e:
            print(f"ERROR trayendo velas de acciones: {type(e).__name__}: {e}", flush=True)
        finally:
            signal.alarm(0)
    elif stocks:
        print("Mercado de acciones cerrado, se saltan este ciclo", flush=True)

    if crypto:
        signal.alarm(60)
        try:
            print(f"Consultando velas de {len(crypto)} pares cripto en lotes...", flush=True)
            crypto_bars = client.get_bars_batch(crypto, crypto=True)
            bars_by_symbol.update(crypto_bars)
            print(f"Recibidas velas de {len(crypto_bars)}/{len(crypto)} pares cripto", flush=True)
        except Exception as e:
            print(f"ERROR trayendo velas de cripto: {type(e).__name__}: {e}", flush=True)
        finally:
            signal.alarm(0)

    trades_this_cycle = 0
    for symbol, df in bars_by_symbol.items():
        try:
            if df.empty or len(df) < params.sma_slow + 1:
                continue

            df = add_indicators(df, params)
            signal_ = latest_signal(df, params)
            if signal_ == "hold":
                continue

            position = positions.get(symbol.replace("/", ""))
            last_price = df["close"].iloc[-1]
            atr = df["atr"].iloc[-1]
            print(f"{symbol}: señal={signal_} precio={last_price:.2f} posición={'sí' if position else 'no'}", flush=True)

            if signal_ == "buy" and position is None:
                qty = risk.position_size(equity, last_price, atr)
                if qty > 0:
                    client.submit_market_order(symbol, qty, "buy")
                    mode = "paper" if config.alpaca_paper else "real"
                    portfolio_state.record_trade(symbol, "buy", qty, last_price, mode)
                    notify(f"🟢 Compra {symbol}: {qty} @ ~{last_price:.2f} ({mode})\nSaldo: ${equity:,.2f}")
                    trades_this_cycle += 1

            elif signal_ == "sell" and position is not None:
                qty = float(position.qty)
                client.submit_market_order(symbol, qty, "sell")
                mode = "paper" if config.alpaca_paper else "real"
                portfolio_state.record_trade(symbol, "sell", qty, last_price, mode)
                notify(f"🔴 Venta {symbol}: {qty} @ ~{last_price:.2f} ({mode})\nSaldo: ${equity:,.2f}")
                trades_this_cycle += 1
        except Exception as e:
            print(f"{symbol}: ERROR evaluando: {type(e).__name__}: {e}", flush=True)
            continue

    print(f"Ciclo completo: {len(bars_by_symbol)} símbolos evaluados, {trades_this_cycle} operaciones", flush=True)


def maybe_reoptimize(client: AlpacaClient, params: StrategyParams, stocks: list[str], crypto: list[str]) -> StrategyParams:
    last_run = get_last_optimized()
    now = datetime.now(timezone.utc)
    if last_run and (now - last_run).days < config.optimizer_interval_days:
        return params

    all_symbols = stocks + crypto
    if not all_symbols:
        return params
    reference_symbol = all_symbols[0]
    ref_bars = client.get_bars_batch([reference_symbol], crypto=client.is_crypto(reference_symbol))
    df = ref_bars.get(reference_symbol)
    if df is None or df.empty:
        return params

    best = optimize(df, config.max_drawdown_pct)
    if best is None:
        save_params(params, now.isoformat())
        return params

    old_params_str = str(params)
    new_params = best.params
    portfolio_state.record_optimizer_run(old_params_str, str(new_params), best.profit_factor)
    save_params(new_params, now.isoformat())
    notify(
        f"🔧 Reoptimización: SMA {new_params.sma_fast}/{new_params.sma_slow}, "
        f"RSI {new_params.rsi_low}-{new_params.rsi_high} "
        f"(profit factor backtest: {best.profit_factor})"
    )
    return new_params


def get_last_summary_date() -> str | None:
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        return data.get("last_summary_date")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_last_summary_date(day_str: str):
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    data["last_summary_date"] = day_str
    with open(STATE_FILE, "w") as f:
        json.dump(data, f)


def maybe_send_daily_summary(client: AlpacaClient, day_start_equity: dict):
    today_str = datetime.now(timezone.utc).date().isoformat()
    if get_last_summary_date() == today_str:
        return
    equity = client.get_equity()
    start = day_start_equity.get("value", equity)
    change = equity - start
    change_pct = (change / start * 100) if start else 0
    positions = client.get_all_positions_by_symbol()
    emoji = "📈" if change >= 0 else "📉"
    notify(
        f"{emoji} Resumen del día\nSaldo: ${equity:,.2f}\n"
        f"Cambio: ${change:,.2f} ({change_pct:+.2f}%)\nPosiciones abiertas: {len(positions)}"
    )
    save_last_summary_date(today_str)
    day_start_equity["value"] = equity


def run_dashboard():
    import uvicorn
    import os
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("dashboard:app", host="0.0.0.0", port=port, log_level="info")


def main():
    print("Arrancando bot...", flush=True)
    problems = config.validate()
    if problems:
        raise SystemExit("Config inválida: " + "; ".join(problems))

    portfolio_state.init_db()
    print("DB inicializada", flush=True)
    client = AlpacaClient()
    print("Cliente Alpaca creado", flush=True)

    print("Resolviendo universo de símbolos (cripto=ALL consulta a Alpaca)...", flush=True)
    stocks, crypto = resolve_universe(client)
    print(f"Universo: {len(stocks)} acciones, {len(crypto)} pares cripto", flush=True)

    risk = RiskManager(config)
    params = load_params()
    day_start_equity = {"value": client.get_equity()}

    import threading
    dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
    dashboard_thread.start()
    print("Dashboard web arrancado en segundo plano", flush=True)

    mode = "PAPER" if config.alpaca_paper else "REAL"
    notify(f"🤖 Bot iniciado en modo {mode}. Universo: {len(stocks)} acciones + {len(crypto)} cripto")
    print("Notificación de arranque enviada, entrando al bucle principal", flush=True)

    while True:
        try:
            params = maybe_reoptimize(client, params, stocks, crypto)
            run_cycle(client, risk, params, stocks, crypto)
            maybe_send_daily_summary(client, day_start_equity)
        except Exception as e:
            notify(f"⚠️ Error en el ciclo: {e}")
        time.sleep(config.loop_interval_minutes * 60)


if __name__ == "__main__":
    main()
