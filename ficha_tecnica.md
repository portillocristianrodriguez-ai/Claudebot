# Ficha técnica — bot-alpaca-ia

Bot de trading automatizado para acciones y criptomonedas, con ajuste adaptativo de parámetros, desplegado en Railway y operando sobre Alpaca (paper → real).

## 1. Objetivo

Sistema que opera de forma autónoma en Alpaca, evalúa señales técnicas cada X minutos, gestiona el riesgo por operación y por cuenta, se reoptimiza periódicamente con datos recientes, y notifica cada acción. Fase 1 en **paper trading**; solo pasa a dinero real cuando las métricas de varias semanas lo justifiquen.

## 2. Arquitectura

```
 datos de mercado (Alpaca Market Data API)
        │
        ▼
 core/strategy.py  ──► señal (buy / sell / hold)
        │
        ▼
 core/risk_manager.py ──► ¿cuánto arriesgar? ¿hay freno activo?
        │
        ▼
 core/alpaca_client.py ──► envía la orden (paper o real, según .env)
        │
        ▼
 core/portfolio_state.py ──► guarda la operación en SQLite (para histórico/app)
        │
        ▼
 core/notifier.py ──► Telegram (Fase 1) / Instagram (Fase 2)

 core/optimizer.py corre aparte, cada N días: revisa el histórico reciente,
 prueba combinaciones de parámetros y actualiza la estrategia si encuentra
 algo mejor. Esa es la pieza que "aprende del mercado".
```

`main.py` orquesta todo en un bucle: es un **worker** de larga duración (no una web app), pensado para el plan `worker: python main.py` de Railway.

## 3. Stack tecnológico

| Pieza | Elección | Motivo |
|---|---|---|
| Lenguaje | Python 3.11 | Mismo stack que `bot-amazon`, ecosistema de trading más maduro |
| Bróker/API | Alpaca (`alpaca-py`) | Acciones + cripto + paper trading gratis, todo con las mismas claves |
| Hosting | Railway (worker service) | Ya lo usas, despliegue desde GitHub, variables de entorno, logs |
| Persistencia | SQLite sobre un Volume de Railway | Histórico de operaciones sobrevive a cada redeploy (lo necesita la futura app) |
| Notificaciones V1 | Telegram Bot API | Ya probado en `bot-amazon`, sin revisión de Meta, funciona en minutos |
| Notificaciones V2 | Instagram (Self Messaging, Graph API) | Viable y documentada por Meta en 2026, pero pide app de Meta + webhook — se monta aparte, no bloquea la V1 |
| Repo | GitHub | Conectado a Railway, deploy automático en cada push |
| Render | No se usa | Railway ya cubre build + worker + variables + logs; Render no aporta nada aquí. Si más adelante montamos un panel web separado del bot, ahí sí tendría sentido evaluarlo |

## 4. Motor de estrategia (V1)

Estrategia de tendencia con filtro, sobre velas diarias/horarias según el activo:

- **Entrada:** cruce alcista de SMA rápida sobre SMA lenta, con RSI(14) entre 40-70 (evita comprar sobrecomprado)
- **Salida:** cruce bajista de las medias, o RSI(14) > 75, o se toca el stop/take-profit
- **Tamaño de posición:** basado en volatilidad (ATR) y en el % de riesgo por operación configurado — no es un tamaño fijo

Parámetros iniciales (`SMA_FAST=20`, `SMA_SLOW=50`, `RSI_LOW=40`, `RSI_HIGH=70`) son un punto de partida razonable, no una promesa de resultado — el optimizador los revisa después.

## 5. El componente "IA" — qué es realmente

Ninguna IA "adivina" el mercado de forma fiable; ni la nuestra ni la de nadie que venda eso. Lo que sí es real y construible:

**Walk-forward optimization**: cada `OPTIMIZER_INTERVAL_DAYS` (por defecto 7), el bot corre un backtest vectorizado sobre la ventana reciente probando una rejilla pequeña de combinaciones de parámetros, y adopta la combinación con mejor *profit factor* que no supere el drawdown máximo permitido. Cada cambio de parámetros queda registrado (fecha, parámetros viejos, nuevos, motivo) — nada de caja negra.

Es la versión honesta de "ajusta el bot según lo que aprende del mercado": se adapta a régimen reciente, con reglas y límites explícitos, no reinforcement learning generando alpha de la nada.

## 6. Gestión de riesgo (innegociable antes de dinero real)

- Riesgo máximo por operación: % configurable del equity (`RISK_PER_TRADE_PCT`, por defecto 1%)
- Pérdida máxima diaria: si se supera (`MAX_DAILY_LOSS_PCT`), el bot deja de abrir posiciones ese día
- Freno de emergencia: si el drawdown desde el máximo histórico supera `MAX_DRAWDOWN_PCT` (10% por defecto), el bot se pausa entero y solo se reactiva a mano
- Exposición máxima por símbolo, para no concentrar todo el capital en un solo activo

## 7. Notificaciones

**V1 (ya incluido):** Telegram — cada orden abierta/cerrada, cada freno activado, cada reoptimización.

**V2 (Instagram, cuando quieras montarlo):** Meta permite en 2026 que una cuenta profesional de Instagram se autoenvíe mensajes ("Self Messaging"), sin la ventana de 24h que aplica a mensajes normales. Pide: cuenta de Instagram profesional, app registrada en Meta con permisos de Business Messaging, y un endpoint con webhook. `notifier.py` ya está escrito para aceptar un segundo canal sin tocar el resto del bot — solo hay que implementar `send_instagram()`.

## 8. Fases

1. **Fase 1 (esto):** bot funcionando en paper trading en Railway, notificando por Telegram, guardando histórico en SQLite
2. **Fase 2:** semanas de paper trading, revisar métricas reales (profit factor, drawdown, win rate), afinar antes de tocar dinero real
3. **Fase 3:** capital real, empezando con muy poco, con los mismos frenos de riesgo activos
4. **Fase 4:** Instagram Self Messaging + API/backend que exponga el histórico de `portfolio_state.py` para una app iOS con gráfica de evolución, operaciones y P&L

## 9. Expectativas realistas

Ni este bot ni ningún otro garantiza rentabilidad alta — quien lo prometa está vendiendo humo. Lo que sí se puede prometer es un sistema con reglas claras, riesgo acotado y que se ajusta con datos en vez de intuición. El criterio para pasar a Fase 3 no es "me apetece", es: semanas de paper trading con métricas que se sostienen.
