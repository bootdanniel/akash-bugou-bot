import os, json, time, random, html, threading, subprocess
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

TG_TOKEN = os.environ.get("TG_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
CF_TOKEN = os.environ.get("CF_TOKEN", "")
CF_ACCOUNT = os.environ.get("CF_ACCOUNT", "")
CF_KV = os.environ.get("CF_KV", "")
CF_KEY = os.environ.get("CF_KEY", "catalogo")
BASE = os.environ.get("BUGOU_BASE", "https://embed.bugoumods.com")
UA = os.environ.get("BUGOU_UA", "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36")
SCRIPT = os.environ.get("EXTRACT_SCRIPT", "/app/f68b.sh")
MAPA_JSON = os.environ.get("MAPA_JSON", "/app/mapa_series_live/mapa_series_live.json")
LOG_FILE = os.environ.get("LOG_FILE", "/app/extracao.log")
OFFSET_FILE = os.environ.get("OFFSET_FILE", "/app/tg_offset.json")

SKIP_EXTRACT = os.environ.get("SKIP_EXTRACT", "0") == "1"
MAX_TEST_LINKS = int(os.environ.get("MAX_TEST_LINKS", "80"))
AUTO_INTERVAL = int(os.environ.get("AUTO_INTERVAL", "3600"))
EXTRACT_TIMEOUT = int(os.environ.get("EXTRACT_TIMEOUT", "3600"))
PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")

LAST_STATUS = {"updated_at": None, "series": 0, "episodios": 0, "canais": 0, "links_testados": 0, "links_ok": 0, "links_fail": 0, "kv_ok": False, "erro": ""}

session = requests.Session()
if PROXY: session.proxies.update({"http": PROXY, "https": PROXY})

def now_str(): return datetime.now(timezone.utc).strftime("%H:%M:%S")
def iso_now(): return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def tg(msg):
    if not TG_TOKEN or not TG_CHAT_ID: return
    msg = str(msg)
    for chunk in [msg[i:i + 3900] for i in range(0, len(msg), 3900)]:
        try: session.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", data={"chat_id": TG_CHAT_ID, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": "true"}, timeout=15)
        except: pass

def tail_file(path, max_chars=1800):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 30000))
            return f.read().decode("utf-8", "replace")[-max_chars:]
    except: return ""

def escape(text): return html.escape(str(text or ""))
def http_headers(extra=None):
    h = {"User-Agent": UA, "Referer": BASE + "/"}
    if extra: h.update(extra)
    return h

def site_check():
    try:
        r = session.get(BASE, headers=http_headers(), timeout=20, allow_redirects=True)
        body = r.text[:200000]
        return r.status_code, "ld(" in body, body[:500], ""
    except Exception as e: return None, False, "", str(e)

def run_extraction():
    if SKIP_EXTRACT: return 0
    env = os.environ.copy(); env.setdefault("BASE", BASE); env.setdefault("UA", UA)
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as log:
            p = subprocess.run(["bash", SCRIPT], stdout=log, stderr=subprocess.STDOUT, env=env, timeout=EXTRACT_TIMEOUT)
        return p.returncode
    except subprocess.TimeoutExpired: return 124
    except Exception as e: return 1

def load_mapa():
    if not os.path.exists(MAPA_JSON): return None, "Arquivo não existe."
    try:
        with open(MAPA_JSON, "r", encoding="utf-8") as f: mapa = json.load(f)
    except Exception as e: return None, f"JSON inválido: {e}"
    totais = mapa.get("totais", {})
    series, canais, episodios = int(totais.get("series", 0)), int(totais.get("canais", 0)), int(totais.get("episodios", 0))
    if series == 0 and canais == 0: return None, "Mapa vazio: series=0 e canais=0."
    mapa["_series"], mapa["_canais"], mapa["_episodios"] = series, canais, episodios
    return mapa, ""

def build_compact(mapa):
    canais = [{"categoria": c.get("categoria", ""), "nome": c.get("nome", ""), "link_final": c.get("link_final")} for c in mapa.get("live", []) if c.get("link_final")]
    series_map = {}
    for s in mapa.get("series", []):
        links = [ep.get("link_final") for ep in s.get("episodios", []) if ep.get("link_final")]
        if links:
            nome = s.get("nome", "")
            if nome not in series_map: series_map[nome] = {"categoria": s.get("categoria", ""), "nome": nome, "links_finais": []}
            series_map[nome]["links_finais"].extend(links)
    return {"atualizado_em": iso_now(), "canais": canais, "series": list(series_map.values())}

def test_link(item):
    tipo, nome, cat, url = item
    try:
        r = session.get(url, headers=http_headers({"Range": "bytes=0-15"}), timeout=15, stream=True, allow_redirects=True)
        ct = (r.headers.get("Content-Type") or "").lower()
        ok = r.status_code in (200, 206) and any(x in ct for x in ("video/", "mpegurl", "mp2t", "octet-stream"))
        r.close(); return item, ok
    except: return item, False

def kv_put(key, payload_bytes):
    if not CF_TOKEN or not CF_ACCOUNT or not CF_KV: return False, "Credenciais CF ausentes"
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/storage/kv/namespaces/{CF_KV}/values/{key}"
    try:
        r = session.put(url, data=payload_bytes, headers={"Authorization": f"Bearer {CF_TOKEN}", "Content-Type": "application/json"}, timeout=60)
        return r.status_code == 200, r.text[:800]
    except Exception as e: return False, str(e)

def ciclo(manual=False):
    global LAST_STATUS; inicio = time.time()
    if manual: tg("🔄 <b>Atualização manual iniciada</b>")
    if not SKIP_EXTRACT:
        code, has_ld, snippet, err = site_check()
        if err or code not in (200, 301, 302) or not has_ld:
            tg(f"❌ <b>Site bloqueou o IP do Akash!</b>\nHTTP: {code} | ld(): {has_ld}\n\n<b>Snippet:</b>\n<pre>{escape(snippet)}</pre>")
            return
    if run_extraction() != 0:
        tg(f"❌ <b>Extração falhou</b>\n<pre>{escape(tail_file(LOG_FILE))}</pre>"); return
    mapa, erro = load_mapa()
    if erro:
        tg(f"❌ <b>Mapa inválido</b>\n{escape(erro)}\nKV não atualizado."); return
    compact = build_compact(mapa)
    all_links = [("canal", c["nome"], c["categoria"], c["link_final"]) for c in compact["canais"]] + [("serie", s["nome"], s["categoria"], url) for s in compact["series"] for url in s["links_finais"]]
    if not all_links:
        tg("❌ <b>Nenhum link encontrado no mapa.</b> KV não atualizado."); return
    test_links = random.sample(all_links, min(len(all_links), MAX_TEST_LINKS))
    ok_count, fail_count = 0, 0
    with ThreadPoolExecutor(max_workers=20) as ex:
        for fut in as_completed([ex.submit(test_link, item) for item in test_links]):
            _, ok = fut.result()
            if ok: ok_count += 1
            else: fail_count += 1
    kv_ok, kv_txt = kv_put(CF_KEY, json.dumps(compact, ensure_ascii=False).encode("utf-8"))
    dur = round(time.time() - inicio, 1)
    LAST_STATUS = {"updated_at": iso_now(), "series": mapa.get("_series"), "episodios": mapa.get("_episodios"), "canais": mapa.get("_canais"), "links_testados": len(test_links), "links_ok": ok_count, "links_fail": fail_count, "kv_ok": kv_ok, "erro": ""}
    msg = f"🔄 <b>Ciclo concluído</b>\n🕐 {now_str()}\n\n• Séries: {mapa.get('_series')}\n• Episódios: {mapa.get('_episodios')}\n• Canais: {mapa.get('_canais')}\n• Amostra testada: {len(test_links)}\n• OK: {ok_count}\n• Falharam: {fail_count}\n• KV: {'✅ Sim' if kv_ok else '❌ Não'}\n• Tempo: {dur}s\n"
    if not kv_ok: msg += f"\n<b>Erro KV:</b>\n<pre>{escape(kv_txt)}</pre>"
    tg(msg)

def ouvir_telegram():
    offset = 0
    while True:
        try:
            r = session.get(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates", params={"offset": offset + 1, "timeout": 30}, timeout=40)
            for upd in r.json().get("result", []):
                offset = int(upd.get("update_id", offset))
                msg = (upd.get("message", {}) or {}).get("text", "").strip()
                if msg == "/start": tg("🤖 <b>Bot Akash</b>\n/atualizar - roda extração\n/status - mostra estado\n/logs - manda log")
                elif msg == "/atualizar": threading.Thread(target=ciclo, args=(True,), daemon=True).start()
                elif msg == "/status": tg(f"📊 <b>Status</b>\nÚltima: {LAST_STATUS.get('updated_at') or 'nunca'}\nSéries: {LAST_STATUS.get('series', 0)}\nCanais: {LAST_STATUS.get('canais', 0)}\nKV: {'✅' if LAST_STATUS.get('kv_ok') else '❌'}")
                elif msg == "/logs": tg(f"📄 <b>Log</b>\n<pre>{escape(tail_file(LOG_FILE))}</pre>")
        except: time.sleep(5)

if __name__ == "__main__":
    print("🤖 Bot iniciado...")
    threading.Thread(target=ouvir_telegram, daemon=True).start()
    while True:
        ciclo(manual=False)
        time.sleep(AUTO_INTERVAL)
