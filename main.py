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
                notify(f"🟢 Compra {symbol}: {qty} @ ~{last_price:.2f} ({mode})")

        elif signal == "sell" and position is not None:
            qty = float(position.qty)
            client.submit_market_order(symbol, qty, "sell")
            mode = "paper" if config.alpaca_paper else "real"
            portfolio_state.record_trade(symbol, "sell", qty, last_price, mode)
            notify(f"🔴 Venta {symbol}: {qty} @ ~{last_price:.2f} ({mode})")


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


def main():
    problems = config.validate()
    if problems:
        raise SystemExit("Config inválida: " + "; ".join(problems))

    portfolio_state.init_db()
    client = AlpacaClient()
    risk = RiskManager(config)
    params = load_params()

    mode = "PAPER" if config.alpaca_paper else "REAL"
    notify(f"🤖 Bot iniciado en modo {mode}. Símbolos: {config.symbols_stocks + config.symbols_crypto}")

    while True:
        try:
            params = maybe_reoptimize(client, params)
            run_cycle(client, risk, params)
        except Exception as e:
            notify(f"⚠️ Error en el ciclo: {e}")
        time.sleep(config.loop_interval_minutes * 60)


if __name__ == "__main__":
    main()
