import os, json, time, gzip, threading, traceback, requests
from datetime import datetime, timezone

# ================= CONFIG =================
TG_TOKEN   = os.environ.get("TG_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
CF_TOKEN   = os.environ.get("CF_TOKEN", "")
CF_ACCOUNT = os.environ.get("CF_ACCOUNT", "")
CF_KV      = os.environ.get("CF_KV", "")
CF_KEY     = os.environ.get("CF_KEY", "catalogo")

PROXY_URL  = "https://bugou-proxy.keriann2203d9.workers.dev?url="
BASE       = "https://embed.bugoumods.com"
HOST_FINAL = "https://teco.bugoumods.com"
PFX_SERIE  = "/series/BugouVortex/BugouVortex"
PFX_LIVE   = "/live/BugouVortex/BugouVortex"
DA         = "embed.bugoumods.com"

SERIES_CAT_NAMES = {
    "1253":"MEXICANAS","1258":"NOVELAS","1266":"GLOBOPLAY","1268":"AMAZON PRIME",
    "1277":"DORAMA","1296":"MINI-SÉRIES","1487":"TURCAS","1488":"TURCAS [LEG]",
}
LIVE_CAT_NAMES = {"1418":"CANAIS 4K","1420":"AMAZON PRIME","1422":"CAZÉ TV"}

SERIES_CATS = [str(i) for i in range(1253, 1310)] + ["1487", "1488"]
LIVE_CATS   = [str(i) for i in range(1418, 1478)] + ["2100000002"]

HEADERS = {"User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"}
sess = requests.Session(); sess.trust_env = False
ULTIMO_UPDATE_ID = 0
KV_HARD_LIMIT = 24_000_000

def cat_nome(d, cid): return d.get(cid) or f"cat_{cid}"

def tg(msg):
    if not (TG_TOKEN and TG_CHAT_ID): return
    for c in [str(msg)[i:i+3900] for i in range(0, len(str(msg)), 3900)]:
        try: sess.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                       json={"chat_id": TG_CHAT_ID, "text": c, "parse_mode": "HTML"}, timeout=10)
        except Exception: pass

def kv_load():
    try:
        r = sess.get(f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/storage/kv/namespaces/{CF_KV}/values/{CF_KEY}",
                     headers={"Authorization": f"Bearer {CF_TOKEN}"}, timeout=20)
        if r.status_code == 200: return r.json(), True
        if r.status_code == 404: return {}, True
        return {}, False
    except Exception:
        return {}, False

def kv_save(dados):
    payload = json.dumps(dados, ensure_ascii=False).encode("utf-8")
    if len(payload) > KV_HARD_LIMIT:
        return False, f"payload {len(payload)} > limite KV {KV_HARD_LIMIT} (não sobrescrevi p/ não corromper)"
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/storage/kv/namespaces/{CF_KV}/values/{CF_KEY}"
    last = ""
    for _ in range(2):
        try:
            r = sess.put(url, headers={"Authorization": f"Bearer {CF_TOKEN}",
                                       "Content-Type": "application/json"},
                         data=payload, timeout=180)
            if r.status_code == 200: return True, ""
            last = f"http {r.status_code}: {r.text[:200]}"
        except Exception as e:
            last = str(e)
        time.sleep(2)
    return False, last

def fetch_via_proxy(target_url):
    safe = target_url.replace("&", "%26")
    try:
        r = sess.get(f"{PROXY_URL}{safe}", headers=HEADERS, timeout=40)
        if r.status_code == 200:
            try: return r.json(), None
            except Exception: return None, "nao-json"
        return None, f"http {r.status_code}"
    except Exception as e:
        return None, f"exc {e}"

def executar_ciclo(manual=False):
    t0 = time.time()
    if manual: tg("🔄 <b>v15 iniciada</b> (Worker + categorias fixas)")

    catalogo, ok = kv_load()
    if not ok:
        tg("❌ <b>Leitura do KV falhou.</b> Ciclo abortado p/ não re-baixar tudo às cegas.\nTente /atualizar de novo em alguns min.")
        return

    series_ids = {str(s.get("series_id")) for s in catalogo.get("series", []) if s.get("series_id")}
    canais_ids = {str(c.get("stream_id")) for c in catalogo.get("canais", []) if c.get("stream_id")}

    novas_s, novas_c = [], []
    falhas = 0
    processed = 0

    for cat in SERIES_CATS:
        processed += 1
        cname = cat_nome(SERIES_CAT_NAMES, cat)
        data, err = fetch_via_proxy(f"{BASE}/index.php?ajax=1&type=series&cat={cat}&_t={int(time.time()*1000)}")
        if not isinstance(data, list):
            falhas += 1
            if processed % 10 == 0: tg(f"⏳ séries {processed}/{len(SERIES_CATS)} | novas {len(novas_s)} | falhas-cat {falhas} | {int(time.time()-t0)}s")
            continue
        for s in data:
            sid = str(s.get("series_id") or "")
            if not sid or sid in series_ids: continue
            info, e2 = fetch_via_proxy(f"{BASE}/index.php?ajax=1&type=series_info&series_id={sid}")
            if not isinstance(info, dict):
                falhas += 1; continue
            eps = []
            for season, arr in (info.get("episodes") or {}).items():
                if not isinstance(arr, list): continue
                for ep in arr:
                    eid = str(ep.get("id") or "")
                    if not eid: continue
                    ext = ep.get("container_extension") or "mp4"
                    eps.append({
                        "t": str(season), "c": str(ep.get("episode_num") or ""),
                        "id": eid, "n": ep.get("title") or (ep.get("info") or {}).get("o_name") or "",
                        "u": f"{HOST_FINAL}/vod.php?type=series&username=BugouVortex&password=BugouVortex&file={eid}.{ext}&domain_auth={DA}",
                    })
            if eps:
                novas_s.append({"series_id": sid, "nome": s.get("name",""), "categoria": cname,
                                "genero": s.get("genre",""), "capa": (s.get("cover","") or "").replace("http://image.tmdb.org","https://image.tmdb.org"),
                                "episodios": eps})
                series_ids.add(sid)
        if processed % 10 == 0:
            tg(f"⏳ séries {processed}/{len(SERIES_CATS)} | novas {len(novas_s)} | falhas {falhas} | {int(time.time()-t0)}s")

    for cat in LIVE_CATS:
        processed += 1
        cname = cat_nome(LIVE_CAT_NAMES, cat)
        data, err = fetch_via_proxy(f"{BASE}/index.php?ajax=1&type=live_streams&cat={cat}&_t={int(time.time()*1000)}")
        if not isinstance(data, list):
            falhas += 1; continue
        for c in data:
            sid = str(c.get("stream_id") or "")
            if not sid or sid in canais_ids: continue
            novas_c.append({"stream_id": sid, "nome": c.get("name",""), "categoria": cname,
                            "logo": (c.get("stream_icon","") or "").replace("http://image.tmdb.org","https://image.tmdb.org"),
                            "epg": c.get("epg_channel_id",""),
                            "u": f"{HOST_FINAL}{PFX_LIVE}/{sid}.m3u8?domain_auth={DA}"})
            canais_ids.add(sid)

    sucesso, erro_kv = True, ""
    if novas_s or novas_c:
        catalogo.setdefault("series", []).extend(novas_s)
        catalogo.setdefault("canais", []).extend(novas_c)
        catalogo["atualizado_em"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        sucesso, erro_kv = kv_save(catalogo)

    dur = int(time.time() - t0)
    msg  = f"🔄 <b>Ciclo v15 concluído</b>\n🕐 {datetime.now(timezone.utc).strftime('%H:%M:%S')}\n\n"
    msg += f"• Séries totais: {len(catalogo.get('series', []))}\n• Canais totais: {len(catalogo.get('canais', []))}\n"
    msg += f"• Novas/Recuperadas: +{len(novas_s)} séries / +{len(novas_c)} canais\n"
    msg += f"• Categorias com falha neste ciclo: {falhas}\n• Tempo: {dur}s\n"
    msg += f"📤 KV: {'✅ Sim' if sucesso else '❌ Não'}"
    if not sucesso: msg += f"\n<pre>{erro_kv[:300]}</pre>"
    tg(msg)

def ouvir_telegram():
    global ULTIMO_UPDATE_ID
    while True:
        try:
            r = sess.get(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates?offset={ULTIMO_UPDATE_ID+1}&timeout=30", timeout=40).json()
            for u in r.get("result", []):
                ULTIMO_UPDATE_ID = u["update_id"]
                txt = (u.get("message", {}) or {}).get("text", "").strip()
                if txt in ("/atualizar", "/recuperar"):
                    threading.Thread(target=executar_ciclo, args=(True,), daemon=True).start()
                elif txt == "/status":
                    d, ok = kv_load()
                    tg(f"📊 <b>Status</b>\nSéries: {len(d.get('series',[]))}\nCanais: {len(d.get('canais',[]))}\nLeitura KV: {'ok' if ok else 'FALHOU'}")
        except Exception:
            time.sleep(5)

def loop_automatico():
    time.sleep(8)
    tg("🤖 <b>Bot Akash v15</b> (Worker + categorias fixas + heartbeat). Full inicial ≈ 45–60 min.")
    executar_ciclo(manual=False)
    while True:
        time.sleep(3600)
        executar_ciclo(manual=False)

if __name__ == "__main__":
    print("🤖 v15 iniciando...", flush=True)
    try:
        threading.Thread(target=ouvir_telegram, daemon=True).start()
        loop_automatico()
    except BaseException:
        traceback.print_exc()
        if os.environ.get("DEBUG_KEEPALIVE") == "1": time.sleep(3600)
        raise
