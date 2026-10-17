#!/usr/bin/env bash
set -u

export LC_ALL=C

BASE="${BASE:-https://embed.bugoumods.com}"
UA="${UA:-Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36}"
T="${T:-20}"
MAPA="${MAPA:-/app/mapa_series_live}"
FALLBACK_CATS="${FALLBACK_CATS:-/app/cats}"

HOST_SERIE="${HOST_SERIE:-https://teco.bugoumods.com}"
PREFIX_SERIE="${PREFIX_SERIE:-/series/BugouVortex/BugouVortex}"
USER_SERIE="${USER_SERIE:-BugouVortex}"
PASS_SERIE="${PASS_SERIE:-BugouVortex}"
DA_SERIE="${DA_SERIE:-embed.bugoumods.com}"

HOST_LIVE="${HOST_LIVE:-https://teco.bugoumods.com}"
PREFIX_LIVE="${PREFIX_LIVE:-/live/BugouVortex/BugouVortex}"
DA_LIVE="${DA_LIVE:-embed.bugoumods.com}"

mkdir -p "$MAPA"/{cats,padroes,logs,series/{json,csv,tsv,json_series},live/lista}

FAIL="$MAPA/logs/falhas.log"
RUN="$MAPA/logs/run.log"
DIAG="$MAPA/logs/diagnostico.txt"

: >> "$FAIL"
: >> "$RUN"
: >> "$DIAG"

log() { printf '%s\n' "$*" | tee -a "$RUN"; }

fetch_code() {
  local url="$1"; local out="$2"; local timeout="${3:-25}"; local code
  code="$(curl -sS --compressed --retry 2 --retry-delay 2 --max-time "$timeout" -A "$UA" -H "Referer: $BASE/" -H "X-Requested-With: XMLHttpRequest" -o "$out" -w '%{http_code}' "$url" 2>>"$DIAG")" || true
  [ -z "$code" ] && code="000"
  printf '%s' "$code"
}

bytes_of() { wc -c < "$1" 2>/dev/null || echo 0; }

log "=============================================="
log "f68b Akash - séries + canais ao vivo"
log "BASE=$BASE"
log "=============================================="

log "FASE 0: categorias"
IDX="$MAPA/index.html"
IDX_CODE="$(fetch_code "$BASE/" "$IDX" 30)"
log "  index_code=$IDX_CODE bytes=$(bytes_of "$IDX")"
printf 'index_code=%s bytes=%s\n' "$IDX_CODE" "$(bytes_of "$IDX")" >> "$DIAG"

CLD="$MAPA/cats_ld.tsv"
grep -oE "ld\([^)]*\)" "$IDX" 2>/dev/null | sed -E "s/^ld\(['\"]([^'\"]+)['\"][[:space:]]*,[[:space:]]*['\"]?([0-9]+)['\"]?[[:space:]]*,[[:space:]]*['\"]([^'\"]*)['\"].*/\1\t\2\t\3/" > "$CLD" || true

awk -F'\t' 'tolower($1) ~ /series/ {print $2"\t"$3}' "$CLD" 2>/dev/null | sort -u > "$MAPA/cats/series.tsv" || true
awk -F'\t' 'tolower($1) ~ /live|channel|canal/ {print $2"\t"$3}' "$CLD" 2>/dev/null | sort -u > "$MAPA/cats/live.tsv" || true

if [ ! -s "$MAPA/cats/series.tsv" ] && [ -s "$FALLBACK_CATS/series.tsv" ]; then cp "$FALLBACK_CATS/series.tsv" "$MAPA/cats/series.tsv"; fi
if [ ! -s "$MAPA/cats/live.tsv" ] && [ -s "$FALLBACK_CATS/live.tsv" ]; then cp "$FALLBACK_CATS/live.tsv" "$MAPA/cats/live.tsv"; fi

if [ ! -s "$MAPA/cats/series.tsv" ] && [ ! -s "$MAPA/cats/live.tsv" ]; then log "ERRO: nenhuma categoria encontrada."; exit 2; fi

log "FASE 1: séries - listando categorias"
ITEMS="$MAPA/series/_items.tsv"; : > "$ITEMS"

while IFS=$'\t' read -r cid cname; do
  [ -n "${cid:-}" ] || continue
  LJ="$MAPA/series/_list_$cid.json"
  CODE="$(fetch_code "$BASE/index.php?ajax=1&type=series&cat=$cid&_t=$(date +%s)000" "$LJ" 25)"
  jq -r --arg cid "$cid" --arg cname "$cname" '(if type=="array" then . else (.series? // .data? // .items? // .list? // []) end)[]? | select(.series_id?) | [(.series_id | tostring),(.name // ""),(.cover // ""),(.genre // ""),$cid,$cname] | @tsv' "$LJ" >> "$ITEMS" 2>/dev/null || true
  rm -f "$LJ"
done < "$MAPA/cats/series.tsv"

awk -F'\t' '!seen[$1]++' "$ITEMS" > "$ITEMS.u" && mv "$ITEMS.u" "$ITEMS"

log "FASE 2: séries - detalhes e links"
cat > "$MAPA/series/w.sh" <<'WS'
#!/usr/bin/env bash
set -u
line="$1"; IFS=$'\t' read -r sid nome capa genero cid cname <<< "$line"
part="$MAPA/series/csv/$sid.csv"; tsv="$MAPA/series/tsv/$sid.tsv"; ser="$MAPA/series/json_series/$sid.json"; info="$MAPA/series/json/$sid.json"
[ -s "$part" ] && [ -s "$tsv" ] && [ -s "$ser" ] && exit 0
if [ ! -s "$info" ]; then
  code="$(curl -sS --compressed --retry 2 --retry-delay 2 --max-time 35 -A "$UA" -H "Referer: $BASE/" -H "X-Requested-With: XMLHttpRequest" -o "$info.tmp" -w '%{http_code}' "$BASE/index.php?ajax=1&type=series_info&series_id=$sid" 2>>"$DIAG")" || true
  if [ "$code" = "200" ]; then mv "$info.tmp" "$info"; else rm -f "$info.tmp"; exit 1; fi
fi
jq -r --arg sid "$sid" --arg nome "$nome" --arg cid "$cid" --arg cname "$cname" --arg capa "$capa" --arg genero "$genero" --arg host "$HOST_SERIE" --arg prefix "$PREFIX_SERIE" --arg da "$DA_SERIE" --arg user "$USER_SERIE" --arg pass "$PASS_SERIE" '(.episodes // {}) | to_entries[] | .key as $s | .value[]? | ((.id // "") | tostring) as $id | ((.container_extension // "mp4") | tostring) as $ext | [ $sid,$nome,$cid,$cname,$capa,$genero,($s | tostring),((.episode_num // "") | tostring),((.title // .info.o_name // "") | tostring),$id,$ext,($host + $prefix + "/" + $id + "." + $ext + "?domain_auth=" + $da),($host + "/vod.php?type=series&username=" + $user + "&password=" + $pass + "&file=" + $id + "." + $ext + "&domain_auth=" + $da) ] | @csv' "$info" > "$part.tmp" 2>>"$FAIL"
jq -c --arg sid "$sid" --arg nome "$nome" --arg cid "$cid" --arg cname "$cname" --arg capa "$capa" --arg genero "$genero" --arg host "$HOST_SERIE" --arg prefix "$PREFIX_SERIE" --arg da "$DA_SERIE" --arg user "$USER_SERIE" --arg pass "$PASS_SERIE" '(.episodes // {}) as $ep | {series_id: $sid,nome: $nome,category_id: $cid,categoria: $cname,capa: $capa,genero: $genero,total_episodios: ([$ep[]? | length] | add // 0),episodios: [ $ep | to_entries[] | .key as $s | .value[]? | ((.id // "") | tostring) as $id | ((.container_extension // "mp4") | tostring) as $ext | {temporada: ($s | tostring),capitulo: ((.episode_num // "") | tostring),titulo: ((.title // .info.o_name // "") | tostring),episode_id: $id,extensao: $ext,link_mp4: ($host + $prefix + "/" + $id + "." + $ext + "?domain_auth=" + $da),link_final: ($host + "/vod.php?type=series&username=" + $user + "&password=" + $pass + "&file=" + $id + "." + $ext + "&domain_auth=" + $da)} ] }' "$info" > "$ser.tmp" 2>>"$FAIL"
[ -s "$part.tmp" ] && [ -s "$ser.tmp" ] && { mv "$part.tmp" "$part"; mv "$ser.tmp" "$ser"; } || { rm -f "$part.tmp" "$ser.tmp"; }
WS
chmod +x "$MAPA/series/w.sh"
export MAPA BASE UA FAIL DIAG HOST_SERIE PREFIX_SERIE USER_SERIE PASS_SERIE DA_SERIE

i=0
while IFS= read -r line; do
  bash "$MAPA/series/w.sh" "$line" &
  i=$((i + 1))
  if [ $((i % T)) -eq 0 ]; then wait; fi
done < "$ITEMS"
wait

log "FASE 3: live - listando canais"
: > "$MAPA/live/_rows.jsonl"
while IFS=$'\t' read -r cid cname; do
  [ -n "${cid:-}" ] || continue
  LJ="$MAPA/live/lista/$cid.json"
  fetch_code "$BASE/index.php?ajax=1&type=live_streams&cat=$cid&_t=$(date +%s)000" "$LJ" 25 > /dev/null
  jq -c --arg cid "$cid" --arg cname "$cname" --arg host "$HOST_LIVE" --arg prefix "$PREFIX_LIVE" --arg da "$DA_LIVE" '(if type=="array" then . else (.live_streams? // .data? // .items? // .list? // []) end)[]? | select(.stream_id?) | ((.stream_id | tostring)) as $sid | {stream_id: $sid,nome: (.name // ""),category_id: $cid,categoria: $cname,logo: (.stream_icon // ""),epg: (.epg_channel_id // ""),extensao_lista: (.container_extension // ""),extensao_real: "m3u8",link_final: ($host + $prefix + "/" + $sid + ".m3u8?domain_auth=" + $da)}' "$LJ" >> "$MAPA/live/_rows.jsonl" 2>/dev/null || true
done < "$MAPA/cats/live.tsv"

log "FASE 4: montando mestres"
if compgen -G "$MAPA/series/json_series/*.json" > /dev/null; then jq -s 'sort_by(.nome)' "$MAPA"/series/json_series/*.json > "$MAPA/series_mestre.json"; else echo "[]" > "$MAPA/series_mestre.json"; fi
if [ -s "$MAPA/live/_rows.jsonl" ]; then jq -s 'sort_by(.nome) | unique_by(.stream_id)' "$MAPA/live/_rows.jsonl" > "$MAPA/canais_mestre.json"; else echo "[]" > "$MAPA/canais_mestre.json"; fi

cats_json() { jq -R -s 'split("\n") | map(select(length > 0) | split("\t") | {category_id: .[0], nome: .[1]})' "$1" 2>/dev/null || echo "[]"; }

jq -n --arg now "$(date -u +%FT%TZ)" --arg base "$BASE" --arg hs "$HOST_SERIE" --arg ps "$PREFIX_SERIE" --arg us "$USER_SERIE" --arg pw "$PASS_SERIE" --arg ds "$DA_SERIE" --arg hl "$HOST_LIVE" --arg pl "$PREFIX_LIVE" --arg dl "$DA_LIVE" --argjson cs "$(cats_json "$MAPA/cats/series.tsv")" --argjson cl "$(cats_json "$MAPA/cats/live.tsv")" --slurpfile SER "$MAPA/series_mestre.json" --slurpfile LI "$MAPA/canais_mestre.json" '{gerado_em: $now, base: $base, padroes: {serie: {host: $hs,prefixo: $ps,username: $us,password: $pw,domain_auth: $ds,modo: "direto_vod_php"},live: {host: $hl,prefixo: $pl,domain_auth: $dl,modo: "direto_m3u8"}},categorias: {series: $cs,live: $cl},totais: {series: ($SER[0] | length),episodios: ([$SER[0][]?.total_episodios] | add // 0),canais: ($LI[0] | length)},series: $SER[0],live: $LI[0]}' > "$MAPA/mapa_series_live.json"
