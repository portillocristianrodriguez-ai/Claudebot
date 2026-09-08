"""
Un único punto de entrada (notify) que reparte a los canales activos.
Añadir Instagram en el futuro es implementar send_instagram() y sumarlo
a la lista de canales — el resto del bot no se entera del cambio.
"""
import sys
import requests
from config import config


def send_telegram(message: str) -> bool:
    if not config.telegram_bot_token or not config.telegram_chat_id:
        print("TELEGRAM: falta bot_token o chat_id", flush=True)
        return False
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": config.telegram_chat_id, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
        if not resp.ok:
            print(f"TELEGRAM ERROR {resp.status_code}: {resp.text}", flush=True)
        else:
            print("TELEGRAM: mensaje enviado OK", flush=True)
        return resp.ok
    except requests.RequestException as e:
        print(f"TELEGRAM EXCEPTION: {e}", flush=True)
        return False


def send_instagram(message: str) -> bool:
    """
    Fase 2. Instagram permite 'Self Messaging' (una cuenta profesional se
    envía mensajes a sí misma, sin la ventana de 24h de los DMs normales),
    pero requiere: cuenta de Instagram profesional, app de Meta con permiso
    de Business Messaging, y un webhook para obtener el ID del destinatario.
    Se deja preparado el punto de entrada; implementar cuando montemos esa app.
    """
    return False


def notify(message: str) -> None:
    send_telegram(message)
    send_instagram(message)
