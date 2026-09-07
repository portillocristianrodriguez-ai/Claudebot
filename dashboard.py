"""
Dashboard de solo lectura: saldo, histórico de equity, posiciones y
operaciones. Corre en el mismo proceso que el bot (mismo contenedor,
mismo acceso directo a la base de datos del Volume) — ver main.py,
que lanza esto en un hilo aparte con uvicorn.

Protegido con HTTP Basic Auth (usuario/contraseña de DASHBOARD_USER /
DASHBOARD_PASSWORD). Es de un solo usuario, así que no hace falta más
que esto por ahora — pero es autenticación real, no un enlace público
sin protección.

De momento es de SOLO LECTURA a propósito: comprar/vender e
ingresos/retiradas desde aquí implican mover dinero real y merece
pensar la seguridad con más calma antes de exponerlo.
"""
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, JSONResponse

from config import config
from alpaca_client import AlpacaClient
import portfolio_state

app = FastAPI()
security = HTTPBasic()
_client = None


def get_client() -> AlpacaClient:
    global _client
    if _client is None:
        _client = AlpacaClient()
    return _client


def check_auth(credentials: HTTPBasicCredentials = Depends(security)):
    user_ok = secrets.compare_digest(credentials.username, config.dashboard_user)
    pass_ok = secrets.compare_digest(credentials.password, config.dashboard_password)
    if not (user_ok and pass_ok):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas", headers={"WWW-Authenticate": "Basic"})
    return True


@app.get("/api/summary")
def api_summary(auth: bool = Depends(check_auth)):
    client = get_client()
    equity = client.get_equity()
    account = client.get_account()
    positions = client.trading.get_all_positions()
    history = portfolio_state.get_equity_history(
        since_iso=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    )
    day_start = history[0]["equity"] if history else equity
    change = equity - day_start
    change_pct = (change / day_start * 100) if day_start else 0
    return JSONResponse({
        "equity": equity,
        "day_change": change,
        "day_change_pct": change_pct,
        "mode": "paper" if config.alpaca_paper else "real",
        "positions": [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc) * 100,
            }
            for p in positions
        ],
    })


@app.get("/api/equity-history")
def api_equity_history(range: str = "1w", auth: bool = Depends(check_auth)):
    days_map = {"1d": 1, "1w": 7, "1m": 30, "all": None}
    days = days_map.get(range, 7)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat() if days else None
    return JSONResponse(portfolio_state.get_equity_history(since_iso=since))


@app.get("/api/trades")
def api_trades(limit: int = 50, auth: bool = Depends(check_auth)):
    return JSONResponse(portfolio_state.get_recent_trades(limit=limit))


@app.get("/", response_class=HTMLResponse)
def index(auth: bool = Depends(check_auth)):
    return HTML_PAGE


HTML_PAGE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>bot-alpaca-ia</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Manrope:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.4/chart.umd.min.js"></script>
<style>
  :root{
    --bg:#10141C; --panel:#171D29; --line:#262E3D;
    --text:#EDEEF2; --muted:#8890A3;
    --gain:#4ADE80; --loss:#FB7185; --accent:#F5B942;
  }
  *{box-sizing:border-box; -webkit-tap-highlight-color:transparent;}
  html,body{margin:0; padding:0; background:var(--bg); color:var(--text);
    font-family:'Manrope',sans-serif; -webkit-font-smoothing:antialiased;}
  body{padding:24px 20px 60px; max-width:560px; margin:0 auto;}
  .mono{font-family:'JetBrains Mono',monospace; font-variant-numeric:tabular-nums;}
  header{display:flex; justify-content:space-between; align-items:baseline; margin-bottom:28px;}
  .brand{font-size:14px; color:var(--muted); letter-spacing:0.02em;}
  .mode{font-size:12px; padding:3px 9px; border-radius:20px; border:1px solid var(--line); color:var(--muted);}
  .hero{margin-bottom:8px;}
  .equity{font-size:52px; font-weight:700; line-height:1.05; letter-spacing:-0.02em;}
  .change{font-size:17px; margin-top:6px; font-weight:600;}
  .change.pos{color:var(--gain);} .change.neg{color:var(--loss);}
  .chart-wrap{margin:28px 0 8px; height:180px;}
  .ranges{display:flex; gap:6px; margin-bottom:24px;}
  .ranges button{flex:1; background:none; border:1px solid var(--line); color:var(--muted);
    padding:8px 0; border-radius:8px; font-family:inherit; font-size:13px; font-weight:600; cursor:pointer;}
  .ranges button.active{background:var(--panel); color:var(--text); border-color:var(--accent);}
  section{margin-top:32px;}
  h2{font-size:15px; font-weight:700; margin:0 0 12px; color:var(--text);}
  .row{display:flex; justify-content:space-between; align-items:center;
    padding:13px 0; border-bottom:1px solid var(--line);}
  .row:last-child{border-bottom:none;}
  .sym{font-weight:700; font-size:15px;}
  .sub{font-size:12px; color:var(--muted); margin-top:2px;}
  .num{text-align:right;}
  .pl.pos{color:var(--gain);} .pl.neg{color:var(--loss);}
  .side{display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:8px;}
  .side.buy{background:var(--gain);} .side.sell{background:var(--loss);}
  .empty{color:var(--muted); font-size:14px; padding:20px 0; text-align:center;}
</style>
</head>
<body>
  <header>
    <div class="brand">bot-alpaca-ia</div>
    <div class="mode mono" id="mode">—</div>
  </header>

  <div class="hero">
    <div class="equity mono" id="equity">$0.00</div>
    <div class="change mono" id="change">—</div>
  </div>

  <div class="chart-wrap"><canvas id="chart"></canvas></div>
  <div class="ranges">
    <button data-range="1d" class="active">1D</button>
    <button data-range="1w">1S</button>
    <button data-range="1m">1M</button>
    <button data-range="all">Todo</button>
  </div>

  <section>
    <h2>Posiciones abiertas</h2>
    <div id="positions"><div class="empty">Cargando…</div></div>
  </section>

  <section>
    <h2>Actividad reciente</h2>
    <div id="trades"><div class="empty">Cargando…</div></div>
  </section>

<script>
const fmt = n => '$' + Number(n).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
const fmtPct = n => (n>=0?'+':'') + Number(n).toFixed(2) + '%';
let chart;

async function loadSummary(){
  const r = await fetch('/api/summary');
  const d = await r.json();
  document.getElementById('mode').textContent = d.mode.toUpperCase();
  document.getElementById('equity').textContent = fmt(d.equity);
  const chEl = document.getElementById('change');
  chEl.textContent = fmt(d.day_change) + '  (' + fmtPct(d.day_change_pct) + ')  hoy';
  chEl.className = 'change mono ' + (d.day_change >= 0 ? 'pos' : 'neg');

  const posEl = document.getElementById('positions');
  if(!d.positions.length){ posEl.innerHTML = '<div class="empty">Sin posiciones abiertas</div>'; }
  else {
    posEl.innerHTML = d.positions.map(p => `
      <div class="row">
        <div><div class="sym">${p.symbol}</div><div class="sub mono">${p.qty} uds</div></div>
        <div class="num">
          <div class="mono">${fmt(p.market_value)}</div>
          <div class="sub mono pl ${p.unrealized_pl>=0?'pos':'neg'}">${fmtPct(p.unrealized_plpc)}</div>
        </div>
      </div>`).join('');
  }
}

async function loadTrades(){
  const r = await fetch('/api/trades?limit=30');
  const d = await r.json();
  const el = document.getElementById('trades');
  if(!d.length){ el.innerHTML = '<div class="empty">Sin operaciones todavía</div>'; return; }
  el.innerHTML = d.map(t => {
    const dt = new Date(t.timestamp);
    const when = dt.toLocaleDateString('es-ES',{day:'2-digit',month:'short'}) + ' · ' + dt.toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'});
    return `
      <div class="row">
        <div><span class="side ${t.side}"></span><span class="sym">${t.symbol}</span>
          <div class="sub">${when}</div></div>
        <div class="num"><div class="mono">${t.qty} @ $${Number(t.price).toFixed(2)}</div>
          <div class="sub">${t.mode}</div></div>
      </div>`;
  }).join('');
}

async function loadChart(range){
  const r = await fetch('/api/equity-history?range=' + range);
  const d = await r.json();
  const labels = d.map(p => new Date(p.timestamp));
  const values = d.map(p => p.equity);
  if(chart) chart.destroy();
  const ctx = document.getElementById('chart').getContext('2d');
  const gradient = ctx.createLinearGradient(0,0,0,180);
  gradient.addColorStop(0, 'rgba(245,185,66,0.25)');
  gradient.addColorStop(1, 'rgba(245,185,66,0)');
  chart = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets: [{ data: values, borderColor: '#F5B942', backgroundColor: gradient,
      fill: true, tension: 0.25, pointRadius: 0, borderWidth: 2 }]},
    options: {
      responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{display:false}, tooltip:{
        callbacks:{ label: c => fmt(c.parsed.y) }, mode:'index', intersect:false } },
      scales:{ x:{display:false}, y:{display:false} },
      interaction:{ mode:'index', intersect:false }
    }
  });
}

document.querySelectorAll('.ranges button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.ranges button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    loadChart(btn.dataset.range);
  });
});

loadSummary(); loadTrades(); loadChart('1d');
setInterval(() => { loadSummary(); loadTrades(); }, 30000);
</script>
</body>
</html>"""
