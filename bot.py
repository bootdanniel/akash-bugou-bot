import os
import re
import json
import time
import threading
import requests
import traceback
from datetime import datetime, timezone

# ================= CONFIGURAÇÕES =================
TG_TOKEN = os.environ.get("TG_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
CF_TOKEN = os.environ.get("CF_TOKEN", "")
CF_ACCOUNT = os.environ.get("CF_ACCOUNT", "")
CF_KV = os.environ.get("CF_KV", "")
CF_KEY = os.environ.get("CF_KEY", "catalogo")

# O NOSSO NOVO PROXY (CLOUDFLARE WORKER)
PROXY_URL = "https://bugou-proxy.keriann2203d9.workers.dev?url="
BASE = "https://embed.bugoumods.com"
HOST_FINAL = "https://teco.bugoumods.com"
PREFIX_SERIE = "/series/BugouVortex/BugouVortex"
PREFIX_LIVE = "/live/BugouVortex/BugouVortex"
DA = "embed.bugoumods.com"

HEADERS = {"User-Agent": "Mozilla/5.0 (Linux; Android 13)"}
sess = requests.Session()
sess.trust_env = False

ULTIMO_UPDATE_ID = 0

# ================= FUNÇÕES BÁSICAS =================
def tg(msg):
    if not TG_TOKEN or not TG_CHAT_ID: return
    for chunk in [str(msg)[i:i+3900] for i in range(0, len(str(msg)), 3900)]:
        try:
            sess.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                          json={"chat_id": TG_CHAT_ID, "text": chunk, "parse_mode": "HTML"}, timeout=10)
        except: pass

def baixar_json_cloudflare():
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/storage/kv/namespaces/{CF_KV}/values/{CF_KEY}"
    try:
        r = sess.get(url, headers={"Authorization": f"Bearer {CF_TOKEN}"}, timeout=15)
        if r.status_code == 200: return r.json()
    except: pass
    return {}

def enviar_json_cloudflare(dados):
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/storage/kv/namespaces/{CF_KV}/values/{CF_KEY}"
    try:
        r = sess.put(url, headers={"Authorization": f"Bearer {CF_TOKEN}"}, data=json.dumps(dados), timeout=60)
        return r.status_code == 200
    except: return False

def fetch_via_proxy(target_url):
    try:
        url = f"{PROXY_URL}{target_url}"
        r = sess.get(url, headers=HEADERS, timeout=30)
        if r.status_code == 200:
            try: return r.json()
            except: return r.text
    except Exception as e:
        print(f"Erro no proxy: {e}")
    return None

# ================= O CÉREBRO =================
def executar_ciclo(manual=False):
    if manual: tg("🔄 <b>Atualização via Cloudflare Worker...</b>")
    
    html = fetch_via_proxy(BASE)
    if not html or not isinstance(html, str):
        tg("❌ <b>Erro ao ler o HTML.</b>\nO Worker falhou ou o site bloqueou.")
        return

    cats = re.findall(r"ld\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]?(\d+)['\"]?", html)
    cats_series = [c[1] for c in cats if "series" in c[0].lower()]
    cats_live = [c[1] for c in cats if any(x in c[0].lower() for x in ["live", "channel", "canal"])]

    if not cats_series and not cats_live:
        tg("⚠️ <b>Nenhuma categoria encontrada.</b>\nO Worker não conseguiu o HTML correto.")
        return

    catalogo = baixar_json_cloudflare()
    series_existentes = {s["nome"] for s in catalogo.get("series", [])}
    canais_existentes = {c["nome"] for c in catalogo.get("canais", [])}
    
    novas_series = []
    novos_canais = []
    
    for cat in cats_series:
        data = fetch_via_proxy(f"{BASE}/index.php?ajax=1&type=series&cat={cat}&_t={int(time.time())}000")
        if not data or not isinstance(data, list): continue
        for s in data:
            nome = s.get("name", "")
            if nome in series_existentes: continue
            
            info = fetch_via_proxy(f"{BASE}/index.php?ajax=1&type=series_info&series_id={s['series_id']}")
            if not info or not isinstance(info, dict): continue
            
            eps = []
            for ep_list in info.get("episodes", {}).values():
                for ep in ep_list:
                    link = f"{HOST_FINAL}{PREFIX_SERIE}/{ep['id']}.{ep.get('container_extension', 'mp4')}?domain_auth={DA}"
                    eps.append(link)
            
            if eps: novas_series.append({"categoria": s.get("genre", ""), "nome": nome, "links_finais": eps})
            time.sleep(0.1)

    for cat in cats_live:
        data = fetch_via_proxy(f"{BASE}/index.php?ajax=1&type=live_streams&cat={cat}&_t={int(time.time())}000")
        if not data or not isinstance(data, list): continue
        for c in data:
            nome = c.get("name", "")
            if nome in canais_existentes: continue
            link = f"{HOST_FINAL}{PREFIX_LIVE}/{c['stream_id']}.m3u8?domain_auth={DA}"
            novos_canais.append({"categoria": c.get("category_id", ""), "nome": nome, "link_final": link})
            time.sleep(0.1)

    if novas_series or novos_canais:
        catalogo.setdefault("series", []).extend(novas_series)
        catalogo.setdefault("canais", []).extend(novos_canais)
        catalogo["atualizado_em"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        sucesso = enviar_json_cloudflare(catalogo)
    else:
        sucesso = True

    msg = f"🔄 <b>Ciclo concluído</b>\n🕐 {datetime.now().strftime('%H:%M:%S')}\n\n"
    msg += f"• Séries Totais: {len(catalogo.get('series', []))}\n• Canais Totais: {len(catalogo.get('canais', []))}\n"
    msg += f"• Novas/Recuperadas: {len(novas_series) + len(novos_canais)}\n"
    msg += f"📤 JSON no Worker: {'✅ Sim' if sucesso else '❌ Não'}"
    tg(msg)

def ouvir_telegram():
    global ULTIMO_UPDATE_ID
    while True:
        try:
            r = sess.get(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates?offset={ULTIMO_UPDATE_ID+1}&timeout=30", timeout=40).json()
            for upd in r.get("result", []):
                ULTIMO_UPDATE_ID = upd["update_id"]
                txt = upd.get("message", {}).get("text", "")
                if txt == "/atualizar" or txt == "/recuperar": 
                    threading.Thread(target=executar_ciclo, args=(True,)).start()
                elif txt == "/status":
                    dados = baixar_json_cloudflare()
                    tg(f"📊 <b>Status</b>\nSéries: {len(dados.get('series', []))}\nCanais: {len(dados.get('canais', []))}")
        except Exception:
            time.sleep(5)

def loop_automatico():
    time.sleep(10)
    tg("🤖 <b>Bot Akash Iniciado! (v11 - Cloudflare Proxy)</b>\nBuscando atualizações...")
    executar_ciclo(manual=False)
    
    while True:
        time.sleep(3600)
        executar_ciclo(manual=False)

if __name__ == "__main__":
    print("🤖 Bot Akash iniciado (v11)...", flush=True)
    threading.Thread(target=ouvir_telegram, daemon=True).start()
    loop_automatico()
