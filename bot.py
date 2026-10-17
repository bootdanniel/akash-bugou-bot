import os, json, time, random, threading, requests, cloudscraper, traceback
from datetime import datetime, timezone

# ================= CONFIGURAÇÕES =================
TG_TOKEN = os.environ.get("TG_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
CF_TOKEN = os.environ.get("CF_TOKEN", "")
CF_ACCOUNT = os.environ.get("CF_ACCOUNT", "")
CF_KV = os.environ.get("CF_KV", "")

BASE = "https://embed.bugoumods.com"
HOST_FINAL = "https://teco.bugoumods.com"
PREFIX_SERIE = "/series/BugouVortex/BugouVortex"
PREFIX_LIVE = "/live/BugouVortex/BugouVortex"
DA = "embed.bugoumods.com"

# O SEGREDO: CloudScraper (burla a Cloudflare)
scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'android', 'mobile': True}
)
scraper.headers.update({"Referer": BASE + "/"})

# Sessão para o Telegram/Cloudflare (sem proxy)
api_session = requests.Session()
api_session.trust_env = False

ULTIMO_UPDATE_ID = 0

def tg(msg):
    if not TG_TOKEN or not TG_CHAT_ID: return
    for chunk in [str(msg)[i:i+3900] for i in range(0, len(str(msg)), 3900)]:
        try:
            api_session.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                          json={"chat_id": TG_CHAT_ID, "text": chunk, "parse_mode": "HTML"}, timeout=10)
        except: pass

def baixar_json_cloudflare():
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/storage/kv/namespaces/{CF_KV}/values/catalogo"
    try:
        r = api_session.get(url, headers={"Authorization": f"Bearer {CF_TOKEN}"}, timeout=15)
        if r.status_code == 200: return r.json()
    except: pass
    return {"canais": [], "series": []}

def enviar_json_cloudflare(dados):
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/storage/kv/namespaces/{CF_KV}/values/catalogo"
    try:
        r = api_session.put(url, headers={"Authorization": f"Bearer {CF_TOKEN}"}, data=json.dumps(dados), timeout=60)
        return r.status_code == 200
    except: return False

def fetch_json(url):
    try:
        time.sleep(random.uniform(0.5, 1.5)) # Pausa para parecer humano
        r = scraper.get(url, timeout=20)
        if r.status_code == 200: return r.json()
        print(f"Erro {r.status_code} na URL: {url}")
    except Exception as e:
        print(f"Exceção: {e}")
    return None

def executar_ciclo(manual=False):
    if manual: tg("🔄 <b>Atualização iniciada (Modo CloudScraper)...</b>")
    
    # 1. Pega o que já temos na nuvem
    catalogo_atual = baixar_json_cloudflare()
    series_existentes = {s["nome"] for s in catalogo_atual.get("series", [])}
    canais_existentes = {c["nome"] for c in catalogo_atual.get("canais", [])}
    
    # 2. Descobre as categorias (usando cloudscraper)
    try:
        html = scraper.get(BASE, timeout=20).text
    except Exception as e:
        tg(f"❌ <b>Erro ao acessar o site:</b>\n{e}")
        return

    import re
    cats = re.findall(r"ld\(['\"]([^'\"]+)['\"][[:space:]]*,[[:space:]]*['\"]?([0-9]+)['\"]?", html)
    cats_series = [c[1] for c in cats if "series" in c[0].lower()]
    cats_live = [c[1] for c in cats if any(x in c[0].lower() for x in ["live", "channel", "canal"])]

    novas_series = []
    novos_canais = []
    
    # 3. Busca apenas o que falta
    for cat in cats_series:
        data = fetch_json(f"{BASE}/index.php?ajax=1&type=series&cat={cat}&_t={int(time.time())}000")
        if not data: continue
        for s in data if isinstance(data, list) else data.get("series", []):
            nome = s.get("name", "")
            if nome in series_existentes: continue
            
            info = fetch_json(f"{BASE}/index.php?ajax=1&type=series_info&series_id={s['series_id']}")
            if not info: continue
            
            eps = []
            for ep_list in info.get("episodes", {}).values():
                for ep in ep_list:
                    link = f"{HOST_FINAL}{PREFIX_SERIE}/{ep['id']}.{ep.get('container_extension', 'mp4')}?domain_auth={DA}"
                    eps.append(link)
            
            if eps: novas_series.append({"categoria": s.get("genre", ""), "nome": nome, "links_finais": eps})

    for cat in cats_live:
        data = fetch_json(f"{BASE}/index.php?ajax=1&type=live_streams&cat={cat}&_t={int(time.time())}000")
        if not data: continue
        for c in data if isinstance(data, list) else data.get("live_streams", []):
            nome = c.get("name", "")
            if nome in canais_existentes: continue
            link = f"{HOST_FINAL}{PREFIX_LIVE}/{c['stream_id']}.m3u8?domain_auth={DA}"
            novos_canais.append({"categoria": c.get("category_id", ""), "nome": nome, "link_final": link})

    # 4. Atualiza o JSON final
    if novas_series or novos_canais:
        catalogo_atual["series"].extend(novas_series)
        catalogo_atual["canais"].extend(novos_canais)
        catalogo_atual["atualizado_em"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        sucesso = enviar_json_cloudflare(catalogo_atual)
    else:
        sucesso = True

    # 5. Manda a mensagem de status
    msg = f"🔄 <b>Ciclo concluído</b>\n🕐 {datetime.now().strftime('%H:%M:%S')}\n\n"
    msg += f"• Séries Totais: {len(catalogo_atual['series'])}\n• Canais Totais: {len(catalogo_atual['canais'])}\n"
    msg += f"• Novas/Recuperadas: {len(novas_series) + len(novos_canais)}\n"
    msg += f"📤 JSON no Worker: {'✅ Sim' if sucesso else '❌ Não'}"
    tg(msg)

def ouvir_telegram():
    global ULTIMO_UPDATE_ID
    while True:
        try:
            r = api_session.get(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates?offset={ULTIMO_UPDATE_ID+1}&timeout=30", timeout=40).json()
            for upd in r.get("result", []):
                ULTIMO_UPDATE_ID = upd["update_id"]
                txt = upd.get("message", {}).get("text", "")
                if txt == "/atualizar": threading.Thread(target=executar_ciclo, args=(True,)).start()
                elif txt == "/status":
                    dados = baixar_json_cloudflare()
                    tg(f"📊 <b>Status</b>\nSéries: {len(dados.get('series', []))}\nCanais: {len(dados.get('canais', []))}\nAtualizado: {dados.get('atualizado_em', 'N/A')}")
        except Exception:
            time.sleep(5)

def loop_automatico():
    time.sleep(10)
    tg("🤖 <b>Bot Akash Iniciado!</b>\nUsando CloudScraper para burlar bloqueio. Primeira verificação...")
    executar_ciclo(manual=False)
    
    while True:
        time.sleep(3600)
        executar_ciclo(manual=False)

def main():
    print("🤖 Bot Akash iniciado (CloudScraper)...", flush=True)
    threading.Thread(target=ouvir_telegram, daemon=True).start()
    loop_automatico()

if __name__ == "__main__":
    try:
        main()
    except BaseException:
        print("💥 ERRO FATAL", flush=True)
        traceback.print_exc()
        time.sleep(3600)
