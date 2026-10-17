import os
import re
import json
import time
import html as html_mod
import random
import threading
import traceback
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# ===================== ENV =====================
TG_TOKEN   = os.environ.get("TG_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
CF_TOKEN   = os.environ.get("CF_TOKEN", "")
CF_ACCOUNT = os.environ.get("CF_ACCOUNT", "")
CF_KV      = os.environ.get("CF_KV", "")
CF_KEY     = os.environ.get("CF_KEY", "catalogo")
CF_KEY_CAT = os.environ.get("CF_KEY_CAT", "catalogo_compacto")

WS_KEY       = os.environ.get("WS_API_KEY", "")
WS_BASE      = "https://api.webscraping.ai/html"
WS_RENDER    = os.environ.get("WS_RENDER", "0") == "1"
WS_CONCURR   = max(1, int(os.environ.get("WS_CONCURRENCY", "3")))
WS_TIMEOUT   = int(os.environ.get("WS_TIMEOUT", "75"))

BUGOU_BASE   = "https://embed.bugoumods.com"
HOST_VOD     = "https://teco.bugoumods.com"
PFX_SERIE    = "/series/BugouVortex/BugouVortex"
PFX_LIVE     = "/live/BugouVortex/BugouVortex"
USER_VOD     = "BugouVortex"
PASS_VOD     = "BugouVortex"
DA           = "embed.bugoumods.com"

AUTO_INTERVAL   = int(os.environ.get("AUTO_INTERVAL", "86400"))
MAX_TEST_LINKS  = int(os.environ.get("MAX_TEST_LINKS", "80"))
FORCE_FULL      = os.environ.get("FORCE_FULL", "0") == "1"
LOG_FILE        = os.environ.get("LOG_FILE", "/app/bot.log")
OFFSET_FILE     = os.environ.get("OFFSET_FILE", "/app/tg_offset.json")

KV_LIMIT_BYTES  = 24_000_000
KV_CHUNK_BYTES  = 18_000_000

sess = requests.Session()
sess.trust_env = False

STATUS = {"updated_at": None, "series": 0, "episodios": 0, "canais": 0, "novas": 0, "kv_ok": False, "erro": "", "modo": "idle"}

def _wlog(s):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f: f.write(s + "\n")
    except: pass

def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    _wlog(s)

def esc(t): return html_mod.escape(str(t or ""))

def tg(msg):
    if not TG_TOKEN or not TG_CHAT_ID: return
    msg = str(msg)
    for i in range(0, len(msg), 3900):
        try:
            sess.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                      data={"chat_id": TG_CHAT_ID, "text": msg[i:i+3900], "parse_mode": "HTML"}, timeout=15)
        except: pass

def tail(path=LOG_FILE, n=1800):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2); sz = f.tell(); f.seek(max(0, sz - 40000))
            return f.read().decode("utf-8", "replace")[-n:]
    except: return ""

# ===================== WEBSCRAPING.AI =====================
def ws_get(url, render=None, tries=3):
    if not WS_KEY: raise RuntimeError("WS_API_KEY ausente")
    render = WS_RENDER if render is None else render
    params = {"url": url, "api_key": WS_KEY}
    if render: params["js"] = "true"
    
    for att in range(1, tries + 1):
        try:
            r = sess.get(WS_BASE, params=params, timeout=WS_TIMEOUT)
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(att * 2 + random.random()); continue
            r.raise_for_status()
            return r.text
        except Exception as e:
            time.sleep(att * 1.5 + random.random())
    raise RuntimeError(f"ws_get falhou para {url[:120]}")

def jparse(text):
    if not text: return None
    t = text.strip()
    starts = [i for i in (t.find("["), t.find("{")) if i >= 0]
    if not starts: return None
    try: return json.loads(t[min(starts):])
    except:
        try: return json.loads(t)
        except: return None

def get_categories():
    body = ws_get(BUGOU_BASE + "/")
    pairs = re.findall(r"""ld\(['"](\w+)['"]\s*,\s*['"]?(\d+)['"]?\s*,\s*['"]([^'"]*)['"]""", body or "")
    series, live = [], []
    for typ, cid, nome in pairs:
        t = typ.lower()
        if "series" in t: series.append((cid, nome))
        elif any(k in t for k in ("live", "channel", "canal")): live.append((cid, nome))
    def uniq(lst):
        seen = set(); out = []
        for c, n in lst:
            if c not in seen: seen.add(c); out.append((c, n))
        return out
    return uniq(series), uniq(live)

def list_series(cid):
    body = ws_get(f"{BUGOU_BASE}/index.php?ajax=1&type=series&cat={cid}&_t={int(time.time()*1000)}")
    j = jparse(body)
    if isinstance(j, dict): j = j.get("series") or j.get("data") or []
    out = []
    for it in (j or []):
        sid = str(it.get("series_id") or "")
        if sid: out.append({"series_id": sid, "name": it.get("name", ""), "cover": it.get("cover", ""), "genre": it.get("genre", "")})
    return out

def list_live(cid):
    body = ws_get(f"{BUGOU_BASE}/index.php?ajax=1&type=live_streams&cat={cid}&_t={int(time.time()*1000)}")
    j = jparse(body)
    if isinstance(j, dict): j = j.get("live_streams") or j.get("data") or []
    out = []
    for it in (j or []):
        sid = str(it.get("stream_id") or "")
        if sid: out.append({"stream_id": sid, "name": it.get("name", ""), "logo": it.get("stream_icon", ""), "epg": it.get("epg_channel_id", ""), "ext_lista": it.get("container_extension", "")})
    return out

def serie_entrada(sid, nome, capa, genero, cid, cname):
    body = ws_get(f"{BUGOU_BASE}/index.php?ajax=1&type=series_info&series_id={sid}")
    info = jparse(body)
    if not isinstance(info, dict): return None
    eps = info.get("episodes") or {}
    episodios = []
    for season, arr in eps.items():
        if not isinstance(arr, list): continue
        for e in arr:
            eid = str(e.get("id") or "")
            ext = str(e.get("container_extension") or "mp4")
            if not eid: continue
            episodios.append({
                "temporada": str(season), "capitulo": str(e.get("episode_num") or ""), "titulo": e.get("title") or "",
                "episode_id": eid, "extensao": ext,
                "link_final": f"{HOST_VOD}/vod.php?type=series&username={USER_VOD}&password={PASS_VOD}&file={eid}.{ext}&domain_auth={DA}"
            })
    if not episodios: return None
    return {"series_id": sid, "nome": nome, "categoria": cname, "capa": capa.replace("http://", "https://"), "genero": genero, "total_episodios": len(episodios), "episodios": episodios}

def canal_entrada(sid, nome, logo, epg, extl, cid, cname):
    return {"stream_id": sid, "nome": nome, "categoria": cname, "logo": logo.replace("http://", "https://"), "epg": epg, "link_final": f"{HOST_VOD}{PFX_LIVE}/{sid}.m3u8?domain_auth={DA}"}

# ===================== MAPA E KV =====================
def build_mapa(prev):
    prev = prev or {}
    prev_idx = {s["series_id"]: s for s in (prev.get("series") or [])}
    series_cats, live_cats = get_categories()
    
    vistos, novos_meta = set(), []
    for cid, cname in series_cats:
        try: items = list_series(cid)
        except: continue
        for it in items:
            sid = it["series_id"]; vistos.add(sid)
            if FORCE_FULL or sid not in prev_idx:
                novos_meta.append((sid, it["name"], it["cover"], it["genre"], cid, cname))

    def mk(m):
        try: return serie_entrada(*m)
        except: return None

    if novos_meta:
        with ThreadPoolExecutor(max_workers=WS_CONCURR) as ex:
            for ent in ex.map(mk, novos_meta):
                if ent: prev_idx[ent["series_id"]] = ent

    series = [prev_idx[sid] for sid in vistos if sid in prev_idx]
    series.sort(key=lambda s: (s.get("nome") or "").lower())

    canais, seen_c = [], set()
    for cid, cname in live_cats:
        try: items = list_live(cid)
        except: continue
        for it in items:
            if it["stream_id"] not in seen_c:
                seen_c.add(it["stream_id"])
                canais.append(canal_entrada(it["stream_id"], it["name"], it["logo"], it["epg"], it["ext_lista"], cid, cname))
    canais.sort(key=lambda c: (c.get("nome") or "").lower())

    return {
        "gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "totais": {"series": len(series), "episodios": sum(s.get("total_episodios", 0) for s in series), "canais": len(canais)},
        "series": series, "live": canais
    }, len(novos_meta)

def build_compact(mapa):
    canais = [{"categoria": c.get("categoria", ""), "nome": c.get("nome", ""), "link_final": c["link_final"]} for c in mapa.get("live", []) if c.get("link_final")]
    smap = {}
    for s in mapa.get("series", []):
        links = [e["link_final"] for e in s.get("episodios", []) if e.get("link_final")]
        if links: smap[s["nome"]] = {"categoria": s.get("categoria", ""), "nome": s["nome"], "links_finais": links}
    return {"atualizado_em": mapa.get("gerado_em"), "canais": canais, "series": list(smap.values())}

def kv_get(key):
    try:
        r = sess.get(f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/storage/kv/namespaces/{CF_KV}/values/{key}", headers={"Authorization": f"Bearer {CF_TOKEN}"}, timeout=30)
        if r.status_code == 200: return r.json()
    except: pass
    return None

def kv_put(key, payload_bytes):
    try:
        r = sess.put(f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/storage/kv/namespaces/{CF_KV}/values/{key}", headers={"Authorization": f"Bearer {CF_TOKEN}"}, data=payload_bytes, timeout=90)
        return r.status_code == 200, r.text[:600]
    except Exception as e: return False, str(e)

def upload(key, obj):
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    return kv_put(key, payload) # Para simplificar, assumindo que não passa de 24MB

# ===================== CICLO =====================
def ciclo(manual=False):
    global STATUS
    t0 = time.time()
    if manual: tg("🔄 <b>Atualização iniciada (webscraping.ai)</b>")
    
    try:
        prev = kv_get(CF_KEY) or {}
        mapa, novas = build_mapa(prev)
        
        if mapa["totais"]["series"] == 0 and mapa["totais"]["canais"] == 0:
            tg("❌ <b>Mapa vazio.</b> O site bloqueou até o webscraping.ai?")
            return
            
        compact = build_compact(mapa)
        kv_ok1, _ = upload(CF_KEY, mapa)
        kv_ok2, _ = upload(CF_KEY_CAT, compact)
        
        STATUS = {"updated_at": mapa["gerado_em"], "series": mapa["totais"]["series"], "episodios": mapa["totais"]["episodios"], "canais": mapa["totais"]["canais"], "novas": novas, "kv_ok": kv_ok1 and kv_ok2, "erro": ""}
        
        dur = round(time.time() - t0, 1)
        msg = f"🔄 <b>Ciclo concluído</b>\n🕐 {datetime.now().strftime('%H:%M:%S')}\n\n• Séries: {STATUS['series']}\n• Episódios: {STATUS['episodios']}\n• Canais: {STATUS['canais']}\n• Novas/info: {novas}\n• KV: {'✅' if STATUS['kv_ok'] else '❌'}\n• Tempo: {dur}s\n"
        tg(msg)
    except Exception as e:
        tg(f"❌ <b>Erro no ciclo</b>\n<pre>{esc(e)}</pre>")

# ===================== TELEGRAM =====================
def listener():
    off = 0
    while True:
        try:
            r = sess.get(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates", params={"offset": off + 1, "timeout": 30}, timeout=40)
            for u in r.json().get("result", []):
                off = int(u.get("update_id", off))
                m = ((u.get("message") or {}).get("text") or "").strip()
                if m == "/start": tg("🤖 <b>Bot Akash + webscraping.ai</b>\n/atualizar • /status • /full")
                elif m == "/atualizar": threading.Thread(target=ciclo, args=(True,), daemon=True).start()
                elif m == "/full":
                    global FORCE_FULL; FORCE_FULL = True
                    threading.Thread(target=ciclo, args=(True,), daemon=True).start()
                elif m == "/status": tg(f"📊 <b>Status</b>\nSéries: {STATUS.get('series',0)}\nCanais: {STATUS.get('canais',0)}\nKV: {'✅' if STATUS.get('kv_ok') else '❌'}")
        except: time.sleep(5)

def main():
    log("🤖 Bot iniciado (Webscraping.ai)")
    threading.Thread(target=listener, daemon=True).start()
    time.sleep(3)
    while True:
        try: ciclo(manual=False)
        except: pass
        time.sleep(AUTO_INTERVAL)

if __name__ == "__main__":
    try: main()
    except BaseException:
        print("💥 ERRO FATAL", flush=True); traceback.print_exc(); time.sleep(3600)
