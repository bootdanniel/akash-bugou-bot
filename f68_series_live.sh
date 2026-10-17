#!/usr/bin/env bash
set -u
BASE="https://embed.bugoumods.com"
UA="Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"
T=20
MAPA="/app/mapa_series_live"

FB_HOST="https://teco.bugoumods.com"
FB_USER="BugouVortex"
FB_PASS="BugouVortex"
FB_DA="embed.bugoumods.com"
FB_PFX_SERIE="/series/BugouVortex/BugouVortex"
FB_PFX_LIVE="/live/BugouVortex/BugouVortex"

mkdir -p "$MAPA"/{cats,padroes,logs,series/{json,csv,tsv,json_series},live/lista}
FAIL="$MAPA/logs/falhas.log"; : >> "$FAIL"
RUN="$MAPA/logs/run.log";     : >> "$RUN"

log(){ printf '%s\n' "$*" | tee -a "$RUN"; }
fetch(){ curl -sS --max-time "${3:-20}" -A "$UA" -H "Referer: $BASE/" -H "X-Requested-With: XMLHttpRequest" "$1" -o "$2" 2>/dev/null || true; }
fetchp(){ curl -sS --max-time "${3:-20}" -A "$UA" -e "$BASE/" "$1" -o "$2" 2>/dev/null || true; }
nitems(){ jq -r 'if type=="array" then length elif type=="object" then ((.vod_streams?//.live_streams?//.series?//.streams?//.data?//.items?//.list?//[])|if type=="array" then length else 0 end) else 0 end' "$1" 2>/dev/null || echo 0; }

log "FASE 0: categorias (series + live)"
IDX="$MAPA/index.html"
fetch "$BASE/" "$IDX" 30
CLD="$MAPA/cats_ld.tsv"
grep -oE "ld\([^)]*\)" "$IDX" 2>/dev/null | sed -E "s/^ld\(['\"]([^'\"]+)['\"][[:space:]]*,[[:space:]]*['\"]?([0-9]+)['\"]?[[:space:]]*,[[:space:]]*['\"]([^'\"]*)['\"].*/\1\t\2\t\3/" > "$CLD" || true
awk -F'\t' '$1 ~ /series/            {print $2"\t"$3}' "$CLD" | sort -u > "$MAPA/cats/series.tsv"
awk -F'\t' '$1 ~ /live|channel|canal/ {print $2"\t"$3}' "$CLD" | sort -u > "$MAPA/cats/live.tsv"
if [ ! -s "$MAPA/cats/series.tsv" ] && [ ! -s "$MAPA/cats/live.tsv" ]; then log "ERRO: nenhuma categoria."; exit 1; fi

log "FASE 1: padroes"
parse_sc(){ local sc="$1" host path query prefix user pass da; host="$(printf '%s' "$sc" | sed -E 's#^(https?://[^/]+).*#\1#')"; path="$(printf '%s' "$sc" | sed -E 's#^https?://[^/]+##; s#\?.*##')"; query="$(printf '%s' "$sc" | sed -n 's/^[^?]*?\(.*\)$/\1/p')"; prefix="${path%/*}"; user="$(printf '%s' "$prefix" | awk -F/ '{print $(NF-1)}')"; pass="$(printf '%s' "$prefix" | awk -F/ '{print $NF}')"; da="$(printf '%s' "$query" | sed -n 's/.*domain_auth=\([^&]*\).*/\1/p')"; [ -z "$da" ] && da="$FB_DA"; printf 'HOST=%s\nPREFIX=%s\nUSER=%s\nPASS=%s\nDA=%s\n' "$host" "$prefix" "$user" "$pass" "$da"; }
get_sc(){ local sc; sc="$(sed -n 's/^[[:space:]]*SC[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$1" 2>/dev/null | head -n1 | sed 's#\\/#/#g')"; [ -z "$sc" ] && sc="$(grep -m1 -oE 'https:[^"]+' "$1" 2>/dev/null | head -n1 | sed 's#\\/#/#g')"; printf '%s' "$sc"; }

SID0=""; while IFS=$'\t' read -r cid _n; do lj="$MAPA/_a_s.json"; fetch "$BASE/index.php?ajax=1&type=series&cat=$cid&_t=$(date +%s)000" "$lj"; [ "$(nitems "$lj")" -gt 0 ] && { SID0="$(jq -r '(if type=="array" then . else (.series?//[]) end)|.[0].series_id//.id//""' "$lj")"; break; }; done < "$MAPA/cats/series.tsv"
if [ -n "$SID0" ]; then ij="$MAPA/_a_si.json"; fetch "$BASE/index.php?ajax=1&type=series_info&series_id=$SID0" "$ij"; EJ="$(jq -r '(.episodes//{})|to_entries[0].value[0].id?//""' "$ij")"; EX="$(jq -r '(.episodes//{})|to_entries[0].value[0].container_extension?//"mp4"' "$ij")"; pj="$MAPA/_a_sp.html"; fetchp "$BASE/player.php?type=vod_streams&id=$EJ&ext=$EX&sid=$SID0&s=1&e=1" "$pj"; SC="$(get_sc "$pj")"; if [ -n "$SC" ]; then parse_sc "$SC" > "$MAPA/padroes/serie.env"; else : > "$MAPA/padroes/serie.env"; fi; else : > "$MAPA/padroes/serie.env"; fi

LSID0=""; while IFS=$'\t' read -r cid _n; do lj="$MAPA/_a_l.json"; fetch "$BASE/index.php?ajax=1&type=live_streams&cat=$cid&_t=$(date +%s)000" "$lj"; [ "$(nitems "$lj")" -gt 0 ] && { LSID0="$(jq -r '(if type=="array" then . else (.live_streams?//[]) end)|.[0].stream_id//""' "$lj")"; break; }; done < "$MAPA/cats/live.tsv"
if [ -n "$LSID0" ]; then pj="$MAPA/_a_lp.html"; fetchp "$BASE/player.php?type=live_streams&id=$LSID0" "$pj"; SC="$(get_sc "$pj")"; if [ -n "$SC" ]; then parse_sc "$SC" > "$MAPA/padroes/live.env"; else : > "$MAPA/padroes/live.env"; fi; else : > "$MAPA/padroes/live.env"; fi

ld_or(){ local k="$1" fb="$2" v; v="$(grep -m1 "^${k}=" "$3" 2>/dev/null | cut -d= -f2-)"; [ -n "$v" ] && printf '%s' "$v" || printf '%s' "$fb"; }
HOST_SERIE="$(ld_or HOST "$FB_HOST" "$MAPA/padroes/serie.env")"; PREFIX_SERIE="$(ld_or PREFIX "$FB_PFX_SERIE" "$MAPA/padroes/serie.env")"; USER_SERIE="$(ld_or USER "$FB_USER" "$MAPA/padroes/serie.env")"; PASS_SERIE="$(ld_or PASS "$FB_PASS" "$MAPA/padroes/serie.env")"; DA_SERIE="$(ld_or DA "$FB_DA" "$MAPA/padroes/serie.env")"
HOST_LIVE="$(ld_or HOST "$FB_HOST" "$MAPA/padroes/live.env")"; PREFIX_LIVE="$(ld_or PREFIX "$FB_PFX_LIVE" "$MAPA/padroes/live.env")"; DA_LIVE="$(ld_or DA "$FB_DA" "$MAPA/padroes/live.env")"

log "FASE 2A: SERIES - listando"
ITEMS="$MAPA/series/_items.tsv"; : > "$ITEMS"
while IFS=$'\t' read -r cid cname; do [ -n "${cid:-}" ] || continue; lj="$MAPA/series/_list_$cid.json"; fetch "$BASE/index.php?ajax=1&type=series&cat=$cid&_t=$(date +%s)000" "$lj"; jq -r --arg cid "$cid" --arg cname "$cname" '(if type=="array" then . else (.series?//.data?//.items?//[]) end)[]? | select(.series_id?) | [(.series_id|tostring),(.name//""),(.cover//""),(.genre//""),$cid,$cname] | @tsv' "$lj" >> "$ITEMS" 2>/dev/null || true; rm -f "$lj"; done < "$MAPA/cats/series.tsv"
awk -F'\t' '!s[$1]++' "$ITEMS" > "$ITEMS.u" && mv "$ITEMS.u" "$ITEMS"

cat > "$MAPA/series/w.sh" <<'WS'
#!/usr/bin/env bash
set -u
line="$1"; IFS=$'\t' read -r sid nome capa genero cid cname <<< "$line"
part="$MAPA/series/csv/$sid.csv"; tsv="$MAPA/series/tsv/$sid.tsv"; ser="$MAPA/series/json_series/$sid.json"; info="$MAPA/series/json/$sid.json"
[ -s "$part" ] && [ -s "$tsv" ] && [ -s "$ser" ] && exit 0
if [ ! -s "$info" ]; then curl -sS --max-time 35 -A "$UA" -H "Referer: $BASE/" -H "X-Requested-With: XMLHttpRequest" "$BASE/index.php?ajax=1&type=series_info&series_id=$sid" -o "$info.tmp" 2>/dev/null && mv "$info.tmp" "$info" || { rm -f "$info.tmp"; echo "erro_info sid=$sid" >> "$FAIL"; exit 1; }; fi
jq -r --arg sid "$sid" --arg nome "$nome" --arg cid "$cid" --arg cname "$cname" --arg capa "$capa" --arg genero "$genero" --arg host "$HOST_SERIE" --arg prefix "$PREFIX_SERIE" --arg da "$DA_SERIE" --arg user "$USER_SERIE" --arg pass "$PASS_SERIE" '(.episodes//{})|to_entries[]|.key as $s|.value[]?|((.id//"")|tostring) as $id|((.container_extension//"mp4")|tostring) as $ext|[ $sid,$nome,$cid,$cname,$capa,$genero,($s|tostring),((.episode_num//"")|tostring),((.title//.info.o_name//"")|tostring),$id,$ext,($host+$prefix+"/"+$id+"."+$ext+"?domain_auth="+$da),($host+"/vod.php?type=series&username="+$user+"&password="+$pass+"&file="+$id+"."+$ext+"&domain_auth="+$da)]|@csv' "$info" > "$part.tmp" 2>>"$FAIL"
jq -r --arg sid "$sid" --arg nome "$nome" --arg cid "$cid" --arg cname "$cname" --arg capa "$capa" --arg genero "$genero" --arg host "$HOST_SERIE" --arg prefix "$PREFIX_SERIE" --arg da "$DA_SERIE" --arg user "$USER_SERIE" --arg pass "$PASS_SERIE" '(.episodes//{})|to_entries[]|.key as $s|.value[]?|((.id//"")|tostring) as $id|((.container_extension//"mp4")|tostring) as $ext|[ $sid,$nome,$cid,$cname,$capa,$genero,($s|tostring),((.episode_num//"")|tostring),((.title//.info.o_name//"")|tostring),$id,$ext,($host+$prefix+"/"+$id+"."+$ext+"?domain_auth="+$da),($host+"/vod.php?type=series&username="+$user+"&password="+$pass+"&file="+$id+"."+$ext+"&domain_auth="+$da)]|@tsv' "$info" > "$tsv.tmp" 2>>"$FAIL"
jq -c --arg sid "$sid" --arg nome "$nome" --arg cid "$cid" --arg cname "$cname" --arg capa "$capa" --arg genero "$genero" --arg host "$HOST_SERIE" --arg prefix "$PREFIX_SERIE" --arg da "$DA_SERIE" --arg user "$USER_SERIE" --arg pass "$PASS_SERIE" '(.episodes//{}) as $ep|{series_id:$sid,nome:$nome,category_id:$cid,categoria:$cname,capa:$capa,genero:$genero,total_episodios:([$ep[]?|length]|add//0),episodios:[$ep|to_entries[]|.key as $s|.value[]?|((.id//"")|tostring) as $id|((.container_extension//"mp4")|tostring) as $ext|{temporada:($s|tostring),capitulo:((.episode_num//"")|tostring),titulo:((.title//.info.o_name//"")|tostring),episode_id:$id,extensao:$ext,link_mp4:($host+$prefix+"/"+$id+"."+$ext+"?domain_auth="+$da),link_final:($host+"/vod.php?type=series&username="+$user+"&password="+$pass+"&file="+$id+"."+$ext+"&domain_auth="+$da)}]}' "$info" > "$ser.tmp" 2>>"$FAIL"
[ -s "$part.tmp" ] && [ -s "$tsv.tmp" ] && [ -s "$ser.tmp" ] && { mv "$part.tmp" "$part"; mv "$tsv.tmp" "$tsv"; mv "$ser.tmp" "$ser"; } || { rm -f "$part.tmp" "$tsv.tmp" "$ser.tmp"; echo "vazio sid=$sid" >> "$FAIL"; }
WS
chmod +x "$MAPA/series/w.sh"
export MAPA BASE UA FAIL HOST_SERIE PREFIX_SERIE USER_SERIE PASS_SERIE DA_SERIE
xargs -d '\n' -P "$T" -n1 bash "$MAPA/series/w.sh" < "$ITEMS" >/dev/null 2>&1 || true

log "FASE 2B: LIVE - listando"
: > "$MAPA/live/_rows.jsonl"
while IFS=$'\t' read -r cid cname; do [ -n "${cid:-}" ] || continue; lj="$MAPA/live/lista/$cid.json"; fetch "$BASE/index.php?ajax=1&type=live_streams&cat=$cid&_t=$(date +%s)000" "$lj"; jq -c --arg cid "$cid" --arg cname "$cname" --arg host "$HOST_LIVE" --arg prefix "$PREFIX_LIVE" --arg da "$DA_LIVE" '(if type=="array" then . else (.live_streams?//.data?//.items?//[]) end)[]? | select(.stream_id?) | ((.stream_id|tostring)) as $sid|{stream_id:$sid,nome:(.name//""),category_id:$cid,categoria:$cname,logo:(.stream_icon//""),epg:(.epg_channel_id//""),extensao_lista:(.container_extension//""),extensao_real:"m3u8",link_final:($host+$prefix+"/"+$sid+".m3u8?domain_auth="+$da)}' "$lj" >> "$MAPA/live/_rows.jsonl" 2>/dev/null || true; done < "$MAPA/cats/live.tsv"

log "FASE 3: montando mestres"
{ echo "series_id,nome,category_id,categoria,capa,genero,temporada,capitulo,titulo,episode_id,extensao,link_mp4,link_final"; cat "$MAPA"/series/csv/*.csv 2>/dev/null; } > "$MAPA/series_mestre.csv"
jq -s 'sort_by(.nome)' "$MAPA"/series/json_series/*.json > "$MAPA/series_mestre.json" 2>>"$FAIL"
jq -s 'sort_by(.nome)|unique_by(.stream_id)' "$MAPA/live/_rows.jsonl" > "$MAPA/canais_mestre.json" 2>>"$FAIL"

cats_json(){ jq -R -s 'split("\n")|map(select(length>0)|split("\t")|{category_id:.[0],nome:.[1]})' "$1" 2>/dev/null || echo '[]'; }
jq -n --arg now "$(date -u +%FT%TZ)" --arg base "$BASE" --arg hs "$HOST_SERIE" --arg ps "$PREFIX_SERIE" --arg us "$USER_SERIE" --arg pw "$PASS_SERIE" --arg ds "$DA_SERIE" --arg hl "$HOST_LIVE" --arg pl "$PREFIX_LIVE" --arg dl "$DA_LIVE" --argjson cs "$(cats_json "$MAPA/cats/series.tsv")" --argjson cl "$(cats_json "$MAPA/cats/live.tsv")" --slurpfile SER "$MAPA/series_mestre.json" --slurpfile LI "$MAPA/canais_mestre.json" '{gerado_em:$now, base:$base, padroes:{serie:{host:$hs,prefixo:$ps,username:$us,password:$pw,domain_auth:$ds,modo:"direto_vod_php"},live:{host:$hl,prefixo:$pl,domain_auth:$dl,modo:"direto_m3u8"}},categorias:{series:$cs,live:$cl},totais:{series:($SER[0]|length),episodios:([$SER[0][]?.total_episodios]|add//0),canais:($LI[0]|length)},series:$SER[0],live:$LI[0]}' > "$MAPA/mapa_series_live.json" 2>>"$FAIL"
