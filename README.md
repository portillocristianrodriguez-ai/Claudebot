# bot-alpaca-ia

Bot de trading para acciones y cripto sobre Alpaca, con reoptimización periódica de parámetros y notificaciones por Telegram. Ver `ficha_tecnica.md` para el diseño completo.

## 1. Alpaca (cuenta paper)

1. Crea cuenta en https://alpaca.markets → Trading API
2. En el dashboard, genera un par de claves de **Paper Trading** (no las live)
3. Guárdalas para el paso 4

## 2. Telegram

Mismo patrón que `bot-amazon`:
1. Habla con `@BotFather` en Telegram → `/newbot` → te da el `TELEGRAM_BOT_TOKEN`
2. Escríbele algo a tu bot nuevo, luego visita `https://api.telegram.org/bot<TOKEN>/getUpdates` para sacar tu `chat_id`

## 3. Subir el proyecto a GitHub

```bash
cd bot-alpaca-ia
git init
git add .
git commit -m "bot-alpaca-ia: versión inicial"
gh repo create bot-alpaca-ia --private --source=. --push
```

(Si no tienes `gh` CLI, crea el repo vacío en github.com y en vez del último comando usa `git remote add origin <url> && git push -u origin main`)

## 4. Railway

El proyecto y el servicio ya están creados (ver el resto de la respuesta). Solo falta:
1. Conectar el repo de GitHub al servicio (dashboard → Settings → Source, o dímelo y lo hago yo)
2. En Variables, añade `ALPACA_API_KEY` y `ALPACA_SECRET_KEY` (las de paper) y `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — el resto de variables ya están puestas con valores por defecto razonables
3. Crea un Volume y móntalo en `/data` (para que el histórico sobreviva a los redeploys) — puedo montarlo yo si me confirmas

## 5. Verificación

Con `ALPACA_PAPER=true`, deja el bot corriendo unos días antes de tocar nada más. Deberías recibir en Telegram: el mensaje de arranque, cada compra/venta, y avisos si se activa algún freno de riesgo.

**No pases a real (`ALPACA_PAPER=false`) hasta tener semanas de datos en paper con métricas que se sostengan.**
