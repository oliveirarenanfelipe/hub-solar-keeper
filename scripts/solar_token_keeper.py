"""
HUB Solar - Token Keeper
Mantem o token do fornecedor solar ativo renovando automaticamente.
Cron a cada 30 min. Cada run dura ~1-2 min.
"""

import os, sys, json, requests, base64, time
from datetime import datetime

SOLAR_API = os.environ.get("SOLAR_API_BASE", "")
GIST_FILE = os.environ.get("GIST_FILENAME", "solar_token.json")


def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')}  {msg}", flush=True)


def tg_send(msg, urgente=False):
    bot  = os.environ.get("TELEGRAM_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot or not chat:
        return
    nivel = "[URGENTE] HUB Solar" if urgente else "[OK] HUB Solar"
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot}/sendMessage",
            json={"chat_id": chat, "text": f"{nivel}\n\n{msg}", "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception:
        pass


def tg_check_novo_token(offset):
    bot  = os.environ.get("TELEGRAM_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot or not chat:
        return None, offset
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{bot}/getUpdates",
            params={"offset": offset, "limit": 20, "timeout": 5},
            timeout=15,
        )
        novo_token = None
        novo_offset = offset
        for u in r.json().get("result", []):
            novo_offset = u["update_id"] + 1
            texto = u.get("message", {}).get("text", "").strip()
            if texto.startswith("eyJ") and len(texto) > 100:
                novo_token = texto
                log(f"Token recebido via Telegram (update {u['update_id']})")
        return novo_token, novo_offset
    except Exception as e:
        log(f"Erro Telegram: {e}")
        return None, offset


def gist_ler(pat, gist_id):
    r = requests.get(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"},
        timeout=15,
    )
    r.raise_for_status()
    return json.loads(r.json()["files"][GIST_FILE]["content"])


def gist_salvar(pat, gist_id, data):
    requests.patch(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"},
        json={"files": {GIST_FILE: {"content": json.dumps(data, indent=2)}}},
        timeout=15,
    ).raise_for_status()


def minutos_restantes(token):
    try:
        part = token.split(".")[1]
        part += "=" * (4 - len(part) % 4)
        payload = json.loads(base64.b64decode(part))
        return (payload.get("exp", 0) - time.time()) / 60
    except Exception:
        return -1


def renovar_token(token):
    try:
        origin = os.environ.get("SOLAR_ORIGIN", "")
        r = requests.get(
            SOLAR_API + "/api/Autenticacao/RenovarAcesso",
            headers={
                "Authorization": f"Bearer {token}",
                "Origin": origin,
                "Referer": origin + "/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            },
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            return data.get("accessToken") or data.get("token"), data
        log(f"Renovacao HTTP {r.status_code}: {r.text[:100]}")
        return None, {}
    except Exception as e:
        log(f"Erro renovacao: {e}")
        return None, {}


def main():
    pat     = os.environ.get("GITHUB_PAT")
    gist_id = os.environ.get("GIST_ID")
    if not pat or not gist_id or not SOLAR_API:
        log("ERRO: variaveis de ambiente nao configuradas.")
        sys.exit(1)

    log("=== HUB Solar - Token Keeper ===")

    try:
        data = gist_ler(pat, gist_id)
    except Exception as e:
        log(f"Erro ao ler estado: {e}")
        tg_send(f"Erro ao ler estado salvo: `{e}`", urgente=True)
        sys.exit(1)

    token  = data.get("accessToken") or data.get("token")
    offset = data.get("telegram_offset", 0)

    novo_token_tg, offset = tg_check_novo_token(offset)
    if novo_token_tg:
        token = novo_token_tg
        tg_send("Token recebido e aceito. Sistema ativo.")

    mins = minutos_restantes(token)
    log(f"Token: {mins:.1f} min restantes")

    if mins <= 0:
        log("Token expirado.")
        tg_send(
            "Token de acesso *expirado*\n\n"
            "Para reativar, envie o token aqui:\n"
            "1. Acesse o portal do fornecedor\n"
            "2. F12 -> Application -> Local Storage\n"
            "3. Copie o valor de `accessToken` e cole aqui",
            urgente=True,
        )
        data["telegram_offset"] = offset
        gist_salvar(pat, gist_id, data)
        sys.exit(1)

    new_token, extra = renovar_token(token)
    if not new_token:
        log("Renovacao falhou.")
        tg_send("Renovacao de token falhou. Envie o token via Telegram para reativar.", urgente=True)
        sys.exit(1)

    new_mins = minutos_restantes(new_token)
    new_data = {"accessToken": new_token, "telegram_offset": offset}
    if "expirationDate" in extra:
        new_data["expirationDate"] = extra["expirationDate"]

    gist_salvar(pat, gist_id, new_data)
    log(f"Token renovado. Proximo vencimento: {new_mins:.0f} min")


if __name__ == "__main__":
    main()
