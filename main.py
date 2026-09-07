"""
Punto de entrada. Pensado para correr como worker de larga duración en
Railway (Procfile: `worker: python main.py`), no como servicio web.
"""
import time
import json
from datetime import datetime, timezone

from config import config
from alpaca_client import AlpacaClient
from strategy import StrategyParams, add_indicators, latest_signal
from risk_manager import RiskManager
from optimizer import optimize
from notifier import notify
import portfolio_state

STATE_FILE = "/data/strategy_state.json"


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


def run_cycle(client: AlpacaClient, risk: RiskManager, params: StrategyParams):
    all_symbols = config.symbols_stocks + config.symbols_crypto
    equity = client.get_equity()
    portfolio_state.record_equity(equity)

    allowed, reason = risk.trading_allowed(equity)
    if not allowed:
        notify(f"⏸️ Trading pausado: {reason}")
        return

    for symbol in all_symbols:
        is_crypto = client.is_crypto(symbol)
        if not is_crypto and not client.is_market_open():
            continue

        df = client.get_bars(symbol)
        if df.empty or len(df) < params.sma_slow + 1:
            continue

        df = add_indicators(df, params)
        signal = latest_signal(df, params)
        position = client.get_open_position(symbol)
        last_price = df["close"].iloc[-1]
        atr = df["atr"].iloc[-1]

        if signal == "buy" and position is None:
            qty = risk.position_size(equity, last_price, atr)
            if qty > 0:
                client.submit_market_order(symbol, qty, "buy")
                mode = "paper" if config.alpaca_paper else "real"
                portfolio_state.record_trade(symbol, "buy", qty, last_price, mode)
                notify(f"🟢 Compra {symbol}: {qty} @ ~{last_price:.2f} ({mode})\nSaldo: ${equity:,.2f}")

        elif signal == "sell" and position is not None:
            qty = float(position.qty)
            client.submit_market_order(symbol, qty, "sell")
            mode = "paper" if config.alpaca_paper else "real"
            portfolio_state.record_trade(symbol, "sell", qty, last_price, mode)
            notify(f"🔴 Venta {symbol}: {qty} @ ~{last_price:.2f} ({mode})\nSaldo: ${equity:,.2f}")


def maybe_reoptimize(client: AlpacaClient, params: StrategyParams) -> StrategyParams:
    last_run = get_last_optimized()
    now = datetime.now(timezone.utc)
    if last_run and (now - last_run).days < config.optimizer_interval_days:
        return params

    # usa el primer símbolo configurado como referencia para reoptimizar
    reference_symbol = (config.symbols_stocks + config.symbols_crypto)[0]
    df = client.get_bars(reference_symbol, lookback_days=200)
    if df.empty:
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
    positions = client.trading.get_all_positions()
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
    risk = RiskManager(config)
    params = load_params()
    day_start_equity = {"value": client.get_equity()}

    import threading
    dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
    dashboard_thread.start()
    print("Dashboard web arrancado en segundo plano", flush=True)

    mode = "PAPER" if config.alpaca_paper else "REAL"
    print(f"Enviando notificación de arranque (modo {mode})...", flush=True)
    notify(f"🤖 Bot iniciado en modo {mode}. Símbolos: {config.symbols_stocks + config.symbols_crypto}")
    print("Notificación de arranque procesada, entrando al bucle principal", flush=True)

    while True:
        try:
            params = maybe_reoptimize(client, params)
            run_cycle(client, risk, params)
            maybe_send_daily_summary(client, day_start_equity)
        except Exception as e:
            notify(f"⚠️ Error en el ciclo: {e}")
        time.sleep(config.loop_interval_minutes * 60)


if __name__ == "__main__":
    main()
