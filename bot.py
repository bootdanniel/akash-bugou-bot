import os, json, subprocess, time, requests, threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

TG_TOKEN = "8873564641:AAG0X6LEzvNf589NvSh_bt9_3b-Twp-IQz8"
TG_CHAT_ID = "8937132507"
CF_TOKEN = "cfut_INympmN4Cf2HVe4R0eFMhzMd8x2IFWYK0zIRLqjr22741237"
CF_ACCOUNT = "91999e708e94f31088fc40d60e089a20"
CF_KV = "504e5f476ade40f1aba5ac319aa9db55"

SCRIPT_BASH = "/app/f68_series_live.sh"
MAPA_JSON = "/app/mapa_series_live/mapa_series_live.json"
ULTIMO_UPDATE = 0

def tg(msg):
    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)

def testar_link(url):
    try:
        r = requests.get(url, stream=True, timeout=10, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://embed.bugoumods.com/"})
        if r.status_code in [200, 206]: return True, url
    except: pass
    return False, url

def rodar_extracao():
    subprocess.run(["bash", SCRIPT_BASH], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def ciclo(manual=False):
    agora = datetime.now().strftime("%H:%M:%S")
    if manual: tg("🔄 <b>Atualização Manual Iniciada...</b>\n⏳ Extraindo links do site...")
    try:
        rodar_extracao()
    except Exception as e:
        tg(f"❌ <b>Erro Crítico na Extração</b>\n<i>{e}</i>")
        return

    if not os.path.exists(MAPA_JSON):
        if manual: tg("❌ <b>Erro</b>\nO JSON não foi gerado.")
        return

    with open(MAPA_JSON, "r", encoding="utf-8") as f: mapa = json.load(f)

    # Prepara a lista de todos os links para testar
    links_para_testar = []
    for c in mapa.get("live", []):
        if c.get("link_final"): links_para_testar.append(("canal", c.get("nome"), c.get("categoria"), c.get("link_final")))
    for s in mapa.get("series", []):
        for ep in s.get("episodios", []):
            if ep.get("link_final"): links_para_testar.append(("serie", s.get("nome"), s.get("categoria"), ep.get("link_final")))

    if manual: tg(f"🔍 Testando {len(links_para_testar)} links em paralelo...")
    
    links_ok = []
    links_falharam = []
    
    # Testa 30 links por vez
    with ThreadPoolExecutor(max_workers=30) as executor:
        resultados = list(executor.map(lambda x: (x, testar_link(x[3])[0]), links_para_testar))

    for item, ok in resultados:
        if ok: links_ok.append(item)
        else: links_falharam.append(item)

    # Monta o JSON final do Cloudflare
    novo_json = {"atualizado_em": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "canais": [], "series": []}
    for tipo, nome, cat, url in links_ok:
        if tipo == "canal":
            novo_json["canais"].append({"categoria": cat, "nome": nome, "link_final": url})
        else:
            # Agrupa episódios da mesma série
            existente = next((item for item in novo_json["series"] if item["nome"] == nome), None)
            if existente: existente["links_finais"].append(url)
            else: novo_json["series"].append({"categoria": cat, "nome": nome, "links_finais": [url]})

    # Envia pro Cloudflare
    r = requests.put(f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/storage/kv/namespaces/{CF_KV}/values/catalogo", headers={"Authorization": f"Bearer {CF_TOKEN}"}, data=json.dumps(novo_json), timeout=30)
    sucesso_cf = r.status_code == 200

    # Estatísticas
    total_links = len(links_para_testar)
    ok_count = len(links_ok)
    falha_count = len(links_falharam)

    msg = f"🔄 <b>Ciclo de Manutenção {'(Manual)' if manual else '(Automático)'}</b>\n🕐 {agora}\n\n"
    msg += f"• Total Testado: {total_links}\n• ✅ OK: {ok_count}\n• ❌ Falharam: {falha_count}\n"
    msg += f"📤 JSON no Worker: {'✅ Sim' if sucesso_cf else '❌ Não'}\n\n"

    if manual and links_falharam:
        msg += "⚠️ <b>Links Não Recuperados:</b>\n"
        for tipo, nome, cat, url in links_falharam[:10]: # Mostra os 10 primeiros para não floodar
            msg += f"• {nome} ({cat})\n"
        if falha_count > 10: msg += f"... e mais {falha_count - 10} links.\n"

    tg(msg)

def loop_automatico():
    while True:
        ciclo(manual=False)
        time.sleep(3600) # 1 hora

def ouvir_telegram():
    global ULTIMO_UPDATE
    while True:
        try:
            res = requests.get(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates?offset={ULTIMO_UPDATE + 1}&timeout=30", timeout=40).json()
            for update in res.get("result", []):
                ULTIMO_UPDATE = update["update_id"]
                msg = update.get("message", {}).get("text", "")
                if msg.strip() == "/atualizar":
                    tg("🔄 <b>Comando recebido!</b> Iniciando atualização sob demanda...")
                    # Roda em uma thread separada para não travar o ouvinte
                    threading.Thread(target=ciclo, args=(True,)).start()
        except Exception:
            time.sleep(5)

if __name__ == "__main__":
    print("🤖 Bot Akash iniciado...")
    # Inicia o ouvinte do Telegram em background
    threading.Thread(target=ouvir_telegram, daemon=True).start()
    # Inicia o loop de 1 hora na thread principal
    loop_automatico()
