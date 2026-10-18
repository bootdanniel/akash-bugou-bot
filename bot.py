import os
import json
import time
import random
import threading
import traceback
import requests
from urllib.parse import quote
from datetime import datetime, timezone

# ================= CONFIG =================
TG_TOKEN   = os.environ.get("TG_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
CF_TOKEN   = os.environ.get("CF_TOKEN", "")
CF_ACCOUNT = os.environ.get("CF_ACCOUNT", "")
CF_KV      = os.environ.get("CF_KV", "")
CF_KEY     = os.environ.get("CF_KEY", "catalogo")

PROXY_URL  = os.environ.get("PROXY_URL", "https://bugou-proxy.keriann2203d9.workers.dev?url=")
BASE       = "https://embed.bugoumods.com"
HOST_FINAL = "https://teco.bugoumods.com"
PFX_LIVE   = "/live/BugouVortex/BugouVortex"
DA         = "embed.bugoumods.com"
USER_VOD = "BugouVortex"
PASS_VOD = "BugouVortex"

# LIMITE POR CICLO: Baixa 50 séries, espera a próxima hora, baixa mais 50...
MAX_SERIES_PER_CYCLE = 50 

HEADERS = {"User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"}
sess = requests.Session()
sess.trust_env = False
ULTIMO_UPDATE_ID = 0
KV_HARD_LIMIT = 24_000_000

SERIES_CATS = [str(i) for i in range(1253, 1310)] + ["1487", "1488"]
LIVE_CATS = [str(i) for i in range(1418, 1478)] + ["2100000002"]

SERIES_CAT_NAMES = {"1253": "MEXICANAS","1258": "NOVELAS","1266": "GLOBOPLAY","1268": "AMAZON PRIME","1277": "DORAMA","1296": "MINI-SÉRIES","1487": "TURCAS","1488": "TURCAS [LEG]"}
LIVE_CAT_NAMES = {"1418": "CANAIS 4K","1419": "+18","1420": "AMAZON PRIME","1422": "CAZÉ TV","2100000002": "MEGA CANAIS"}

def cat_nome(table, cid): return table.get(cid) or f"cat_{cid}"

def tg(msg):
    if not (TG_TOKEN and TG_CHAT_ID): return
    msg = str(msg)
    for i in range(0, len(msg), 3900):
        try:
            sess.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", json={"chat_id": TG_CHAT_ID, "text": msg[i:i + 3900], "parse_mode": "HTML", "disable_web_page_preview": "true"}, timeout=15)
        except Exception: pass

def kv_load():
    try:
        r = sess.get(f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/storage/kv/namespaces/{CF_KV}/values/{CF_KEY}", headers={"Authorization": f"Bearer {CF_TOKEN}"}, timeout=25)
        if r.status_code == 200: return r.json(), True
        if r.status_code == 404: return {}, True
        return {}, False
    except Exception: return {}, False

def kv_save(dados):
    payload = json.dumps(dados, ensure_ascii=False).encode("utf-8")
    if len(payload) > KV_HARD_LIMIT: return False, f"payload > limite KV"
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/storage/kv/namespaces/{CF_KV}/values/{CF_KEY}"
    last = ""
    for _ in range(2):
        try:
            r = sess.put(url, headers={"Authorization": f"Bearer {CF_TOKEN}", "Content-Type": "application/json"}, data=payload, timeout=180)
            if r.status_code == 200: return True, ""
            last = f"http {r.status_code}: {r.text[:250]}"
        except Exception as e: last = str(e)
        time.sleep(2)
    return False, last

def extract_json(text):
    if not text: return None
    t = text.strip()
    try: return json.loads(t)
    except Exception: pass
    for opener, closer in (("[", "]"), ("{", "}")):
        i = t.find(opener)
        if i < 0: continue
        try: return json.loads(t[i:])
        except Exception: pass
        j = t.rfind(closer)
        if j > i:
            try: return json.loads(t[i:j + 1])
            except Exception: pass
    return None

def http_get_proxy(target, tries=3):
    full = PROXY_URL + quote(target, safe="")
    last_err = None
    last_snip = ""
    for attempt in range(tries):
        try:
            r = sess.get(full, headers=HEADERS, timeout=45)
            last_snip = (r.text or "")[:300]
            if r.status_code in (429, 500, 502, 503, 504):
                last_err = f"http {r.status_code}"
                time.sleep(5 + attempt * 5 + random.random() * 2) # Espera maior se tomar block
                continue
            if r.status_code != 200:
                last_err = f"http {r.status_code}"
                time.sleep(2 + attempt)
                continue
            try: j = r.json()
            except Exception: j = extract_json(r.text)
            if j is None:
                last_err = "nao-json"
                time.sleep(2 + attempt * 2)
                continue
            return j, None, last_snip
        except Exception as e:
            last_err = f"exc {e}"
            time.sleep(2 + attempt * 2)
    return None, last_err, last_snip

def as_list(j):
    if isinstance(j, list): return j
    if isinstance(j, dict):
        for k in ("series", "data", "items", "list", "results", "vod_streams", "live_streams", "streams", "channels"):
            v = j.get(k)
            if isinstance(v, list): return v
        for v in j.values():
            if isinstance(v, list): return v
    return None

def norm_img(url): return (url or "").replace("http://image.tmdb.org", "https://image.tmdb.org")

def serie_link_final(episode_id, ext):
    return f"{HOST_FINAL}/vod.php?type=series&username={USER_VOD}&password={PASS_VOD}&file={episode_id}.{ext}&domain_auth={DA}"

def live_link_final(stream_id):
    return f"{HOST_FINAL}{PFX_LIVE}/{stream_id}.m3u8?domain_auth={DA}"

def executar_ciclo(manual=False):
    t0 = time.time()
    if manual: tg("🔄 <b>v18 iniciada</b>")
    catalogo, ok = kv_load()
    if not ok:
        tg("❌ <b>Leitura do KV falhou.</b>")
        return

    series_ids = set(str(s.get("series_id") or "") for s in catalogo.get("series", []) if s.get("series_id"))
    canais_ids = set(str(c.get("stream_id") or "") for c in catalogo.get("canais", []) if c.get("stream_id"))

    novas_s, novas_c = [], []
    cat_report, info_falhas = [], []
    ok_cats = empty_cats = fail_cats = 0
    
    processados_neste_ciclo = 0

    for idx, cat in enumerate(SERIES_CATS, 1):
        if processados_neste_ciclo >= MAX_SERIES_PER_CYCLE: break
        
        cname = cat_nome(SERIES_CAT_NAMES, cat)
        target = f"{BASE}/index.php?ajax=1&type=series&cat={cat}&_t={int(time.time() * 1000)}"
        j, err, snip = http_get_proxy(target)
        arr = as_list(j)

        if arr is None:
            fail_cats += 1
            cat_report.append({"cat": cat, "nome": cname, "tipo": "LIST_FAIL", "erro": err or "not-list", "amostra": snip[:180]})
        elif len(arr) == 0:
            empty_cats += 1
            cat_report.append({"cat": cat, "nome": cname, "tipo": "EMPTY"})
        else:
            ok_cats += 1
            cat_report.append({"cat": cat, "nome": cname, "tipo": "OK", "itens": len(arr)})
            for s in arr:
                if processados_neste_ciclo >= MAX_SERIES_PER_CYCLE: break
                
                sid = str(s.get("series_id") or s.get("id") or "")
                nome = s.get("name") or s.get("title") or ""
                if not sid or sid in series_ids: continue
                info_target = f"{BASE}/index.php?ajax=1&type=series_info&series_id={sid}"
                info, e2, s2 = http_get_proxy(info_target)
                
                if not isinstance(info, dict) or ("episodes" not in info and "seasons" not in info):
                    info_falhas.append({"sid": sid, "nome": nome, "cat": cat, "erro": e2 or "sem_episodes", "amostra": s2[:180]})
                    time.sleep(2) # Pausa maior se der erro
                    continue
                
                eps = []
                raw_eps = info.get("episodes") or info.get("seasons") or []
                if isinstance(raw_eps, dict): iterator = raw_eps.items()
                elif isinstance(raw_eps, list): iterator = enumerate(raw_eps)
                else: iterator = []

                for season, arr_ep in iterator:
                    if not isinstance(arr_ep, list): continue
                    for ep in arr_ep:
                        if not isinstance(ep, dict): continue
                        eid = str(ep.get("id") or ep.get("episode_id") or "")
                        if not eid: continue
                        ext = ep.get("container_extension") or ep.get("ext") or "mp4"
                        eps.append({"t": str(season), "c": str(ep.get("episode_num") or ep.get("episode") or ""), "id": eid, "n": ep.get("title") or (ep.get("info") or {}).get("o_name") or "", "u": serie_link_final(eid, ext)})
                
                if eps:
                    novas_s.append({"series_id": sid, "nome": nome, "category_id": cat, "categoria": cname, "genero": s.get("genre") or "", "capa": norm_img(s.get("cover") or ""), "total_episodios": len(eps), "episodios": eps})
                    series_ids.add(sid)
                    processados_neste_ciclo += 1
                
                # PAUSA OBRIGATÓRIA DE 1.5s ENTRE SÉRIES
                time.sleep(1.5 + random.random() * 1.0)

        if processados_neste_ciclo > 0 and processados_neste_ciclo % 10 == 0:
            tg(f"⏳ Progresso: {processados_neste_ciclo}/{MAX_SERIES_PER_CYCLE} séries baixadas. Aguardando...")
            
        time.sleep(1) # Pausa entre categorias

    # (Live category fetching unchanged for brevity, it usually doesn't get blocked as hard)
    for idx, cat in enumerate(LIVE_CATS, 1):
        cname = cat_nome(LIVE_CAT_NAMES, cat)
        target = f"{BASE}/index.php?ajax=1&type=live_streams&cat={cat}&_t={int(time.time() * 1000)}"
        j, err, snip = http_get_proxy(target)
        arr = as_list(j)
        if isinstance(arr, list):
            for c in arr:
                sid = str(c.get("stream_id") or c.get("id") or "")
                nome = c.get("name") or c.get("title") or ""
                if not sid or sid in canais_ids: continue
                novas_c.append({"stream_id": sid, "nome": nome, "category_id": cat, "categoria": cname, "logo": norm_img(c.get("stream_icon") or ""), "epg": c.get("epg_channel_id") or "", "extensao_lista": c.get("container_extension") or "", "extensao_real": "m3u8", "u": live_link_final(sid)})
                canais_ids.add(sid)
        time.sleep(1)

    sucesso = True
    if novas_s or novas_c:
        catalogo.setdefault("series", []).extend(novas_s)
        catalogo.setdefault("canais", []).extend(novos_c)
        catalogo["atualizado_em"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        sucesso, erro_kv = kv_save(catalogo)

    dur = int(time.time() - t0)
    msg = f"🔄 <b>Ciclo v18 concluído (Cotas de Segurança)</b>\n🕐 {datetime.now(timezone.utc).strftime('%H:%M:%S')}\n\n• Séries totais: {len(catalogo.get('series', []))}\n• Canais totais: {len(catalogo.get('canais', []))}\n• Baixadas neste ciclo: +{len(novas_s)} séries / +{len(novas_c)} canais\n• Tempo: {dur}s\n📤 KV: {'✅ Sim' if sucesso else '❌ Não'}"
    
    if info_falhas:
        msg += f"\n\n⚠️ Séries com falha na API: {len(info_falhas)}\n(A maioria será tentada novamente na próxima hora)."
        
    tg(msg)

def ouvir_telegram():
    global ULTIMO_UPDATE_ID
    while True:
        try:
            r = sess.get(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates", params={"offset": ULTIMO_UPDATE_ID + 1, "timeout": 30}, timeout=40).json()
            for upd in r.get("result", []):
                ULTIMO_UPDATE_ID = int(upd.get("update_id", ULTIMO_UPDATE_ID))
                txt = ((upd.get("message") or {}).get("text") or "").strip()
                if txt in ("/atualizar", "/recuperar"): 
                    tg("🔄 Forçando atualização manual (respeitando o limite de 50 séries)...")
                    threading.Thread(target=executar_ciclo, args=(True,), daemon=True).start()
        except Exception: time.sleep(5)

def loop_automatico():
    time.sleep(8)
    tg("🤖 <b>Bot Akash v18 (Modo Paciência)</b>\nPara não ser bloqueado pelo site, vou baixar 50 séries por hora. Isso pode levar alguns dias, mas é 100% seguro e automático.")
    executar_ciclo(manual=False)
    while True:
        time.sleep(3600) # Verifica de hora em hora
        executar_ciclo(manual=False)

if __name__ == "__main__":
    print("🤖 v18 iniciando...", flush=True)
    try:
        threading.Thread(target=ouvir_telegram, daemon=True).start()
        loop_automatico()
    except BaseException:
        traceback.print_exc()
        if os.environ.get("DEBUG_KEEPALIVE") == "1": time.sleep(3600)
        raise
