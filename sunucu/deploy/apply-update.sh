#!/usr/bin/env bash
# Kanıt Paneli güvenli uygulama-kodu güncellemesi (2.1 -> 2.2 -> 2.3 ...).
# Bu betik ZIP açmaz, paket indirmez, apt kurulumu yapmaz ve Plesk/Nginx/HTTPS yapılandırmasına dokunmaz.
# pip yalnız requirements.txt'te SABİT SÜRÜM YÜKSELTMESİ varsa (örn. Pillow==12.3.0 -> 13.0.0) ve yalnız
# /opt/kanit-paneli/.venv içinde çalıştırılır; yeni paket adı eklenmişse betik durur. Birim dosyaları
# (deploy/kanit-web.service, kanit-bot.service) /etc/systemd/system'dekinden farklıysa yedeklenip güncellenir.
# Kaynak kök, bu deploy dizininin bir üstüdür.
set -Eeuo pipefail
IFS=$'\n\t'
if [[ -z "${KANIT_TEST:-}" ]]; then
    PATH=/usr/sbin:/usr/bin:/sbin:/bin
    export PATH
fi

# Test/prova ortamı için ezilebilir değerler (canlı sunucuda değiştirmeyin).
readonly DEST="${KANIT_DEST:-/opt/kanit-paneli}"
readonly DATA_DIR="$DEST/data"
readonly ENV_FILE="$DEST/.env"
readonly DB_FILE="$DEST/data/panel.db"
readonly VENV_PY="${KANIT_VENV_PY:-$DEST/.venv/bin/python}"
readonly WEB_SERVICE=kanit-web.service
readonly BOT_SERVICE=kanit-bot.service
readonly BACKUP_ROOT="${KANIT_BACKUP_ROOT:-/var/backups/kanit-paneli}"
readonly UNIT_DIR="${KANIT_UNIT_DIR:-/etc/systemd/system}"
readonly HEALTH_URL="${KANIT_HEALTH_URL:-http://127.0.0.1:18080/saglik}"
readonly SYSTEMCTL="${KANIT_SYSTEMCTL:-systemctl}"
readonly SERVICE_USER="${KANIT_USER:-kanit}"
readonly PREFLIGHT_SECRET='kanit-update-preflight-only-0123456789abcdef0123456789abcdef'
# pip komutu (test ortamında sahte pip verilebilir; boşluklarla ayrılmış).
PIP_CMD_STR="${KANIT_PIP:-$VENV_PY -m pip}"
IFS=' ' read -r -a PIP_CMD <<<"$PIP_CMD_STR"

SCRIPT_DIR="$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SOURCE_ROOT="$(CDPATH='' cd -- "$SCRIPT_DIR/.." && pwd -P)"
HELPER="$SCRIPT_DIR/update-support.py"
DRY_RUN=0

usage() {
    cat <<'USAGE'
Kullanım: sudo bash deploy/apply-update.sh [--dry-run]

Kaynak, bu betiğin bulunduğu deploy dizininin üst köküdür. Hedef sabittir:
/opt/kanit-paneli. --dry-run yalnız okuyarak ön koşulları, uyumluluğu, servis
aktifliğini, bağımlılık ve birim dosyası farklarını raporlar; yedek, dosya,
veritabanı veya servis değişikliği yapmaz.
USAGE
}

case "${1:-}" in
    '') ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help|--yardim) usage; exit 0 ;;
    *) echo "HATA: Bilinmeyen seçenek. --help kullanın." >&2; exit 2 ;;
esac

fatal() {
    local code="$1"
    shift
    echo "HATA [$code]: $*" >&2
    exit "$code"
}

pause_update() {
    local code="$1"
    shift
    echo "DURAKLATILDI [$code]: $*" >&2
    echo "Otomatik apt kurulumu ve yapılandırma değişikliği yapılmadı." >&2
    exit "$code"
}

need_command() {
    command -v "$1" >/dev/null 2>&1 || fatal 11 "Gerekli komut bulunamadı: $1"
}

service_is_active() {
    "$SYSTEMCTL" is-active --quiet "$1"
}

status_label() {
    if [[ "$1" == 1 ]]; then printf 'aktif'; else printf 'pasif'; fi
}

if [[ ${EUID} -ne 0 ]]; then
    fatal 10 "Bu betik root olarak çalıştırılmalı (sudo bash deploy/apply-update.sh)."
fi

for bin in python3 runuser curl sha256sum stat cmp cp mv find chown chmod install mktemp awk sleep cat rm date env diff; do
    need_command "$bin"
done
command -v "$SYSTEMCTL" >/dev/null 2>&1 || fatal 11 "Gerekli komut bulunamadı: $SYSTEMCTL"

[[ -f "$HELPER" && ! -L "$HELPER" && -r "$HELPER" ]] || \
    fatal 11 "update-support.py kaynak pakette okunabilir normal dosya değil. ZIP'i önce kullanıcı olarak açın."
[[ "$SOURCE_ROOT" != "$DEST" ]] || \
    fatal 11 "Kaynak paket $DEST olamaz; açılmış yeni paketin deploy/apply-update.sh betiğini çalıştırın."

# Yalnız okuyan kaynak derleme denetimi: __pycache__ oluşturmaz.
if ! python3 "$HELPER" source-check --root "$SOURCE_ROOT" >/dev/null; then
    fatal 12 "Kaynak app/ veya requirements.txt doğrulanamadı; hiçbir canlı dosya değiştirilmedi."
fi

[[ -d "$DEST" && ! -L "$DEST" ]] || fatal 13 "Hedef $DEST normal dizin değil."
[[ -d "$DEST/app" && ! -L "$DEST/app" ]] || fatal 13 "Mevcut app dizini normal dizin değil."
[[ -f "$DEST/requirements.txt" && ! -L "$DEST/requirements.txt" && -r "$DEST/requirements.txt" ]] || \
    fatal 13 "Hedef requirements.txt okunamıyor."
[[ -x "$VENV_PY" ]] || fatal 13 ".venv/bin/python çalıştırılabilir değil."
[[ -d "$DATA_DIR" && ! -L "$DATA_DIR" ]] || fatal 13 "PANEL_VERI dizini beklenen normal dizin değil."
[[ -f "$DB_FILE" && ! -L "$DB_FILE" ]] || fatal 13 "Beklenen SQLite dosyası data/panel.db bulunamadı."
id "$SERVICE_USER" >/dev/null 2>&1 || fatal 13 "$SERVICE_USER servis hesabı bulunamadı."
KANIT_GID="$(id -g "$SERVICE_USER")"

# .env asla shell source edilmez. Yardımcı yalnız beklenen ağ/veri ayarlarını
# denetler ve hiçbir değer yazdırmaz.
if ! python3 "$HELPER" env-check --env "$ENV_FILE" --owner 0 --group "$KANIT_GID" --panel-veri "$DATA_DIR" >/dev/null; then
    fatal 14 ".env özel izin/sahiplik veya PANEL_VERI/DINLE/PORT/HTTPS/TRUST_PROXY uyumluluğunu sağlamıyor."
fi
if ! runuser -u "$SERVICE_USER" -- test -r "$ENV_FILE"; then
    fatal 14 "$SERVICE_USER hesabı .env dosyasını okuyamıyor; servis başlatılması güvenli değil."
fi
if ! runuser -u "$SERVICE_USER" -- test -r "$DB_FILE" -a -w "$DATA_DIR"; then
    fatal 14 "$SERVICE_USER hesabı SQLite kaynağını okuyamıyor veya geçici snapshot dizinine yazamıyor."
fi
if ! runuser -u "$SERVICE_USER" -- test -r "$DEST/app/__init__.py" -a -x "$DEST/app"; then
    fatal 14 "$SERVICE_USER hesabı mevcut app kodunu okuyamıyor."
fi
if ! runuser -u "$SERVICE_USER" -- "$VENV_PY" -c 'import sys; assert sys.version_info >= (3, 8)' >/dev/null 2>&1; then
    fatal 14 ".venv Python $SERVICE_USER hesabıyla çalışma denetiminden geçmedi."
fi

# Bağımlılık beyanı: yalnız sabitlenmiş SÜRÜM YÜKSELTMESİ kabul edilir (update-support.py requirements-diff).
# Yeni paket adı, kaldırılan paket, sürüm düşürme veya serbest sürüm -> betik pip çalıştırmadan durur.
REQ_CHANGED=0
REQ_UPGRADE=0
REQ_DIFF_OUT=''
if ! cmp -s "$SOURCE_ROOT/requirements.txt" "$DEST/requirements.txt"; then
    REQ_CHANGED=1
    if ! REQ_DIFF_OUT="$(python3 "$HELPER" requirements-diff --old "$DEST/requirements.txt" --new "$SOURCE_ROOT/requirements.txt" 2>&1)"; then
        printf '%s\n' "$REQ_DIFF_OUT" >&2
        pause_update 20 "requirements.txt değişmiş ve bu değişiklik yalnız sürüm yükseltmesi değil. Bu betik yeni paket kurmaz; bağımlılıkları elle doğrulayıp onaylı bakımda güncelleyin."
    fi
    if grep -q '^GEREKSINIMLER_YUKSELTME$' <<<"$REQ_DIFF_OUT"; then REQ_UPGRADE=1; fi
fi

# Birim dosyaları: deploy/*.service ile kurulu olanlar farklıysa güncellenecek.
UNITS_TO_SYNC=()
for unit in "$WEB_SERVICE" "$BOT_SERVICE"; do
    if [[ -f "$SOURCE_ROOT/deploy/$unit" ]] && ! cmp -s "$SOURCE_ROOT/deploy/$unit" "$UNIT_DIR/$unit"; then
        UNITS_TO_SYNC+=("$unit")
    fi
done

UNITS_LIST="$(IFS=' '; printf '%s' "${UNITS_TO_SYNC[*]}")"

WEB_WAS_ACTIVE=0
BOT_WAS_ACTIVE=0
if service_is_active "$WEB_SERVICE"; then WEB_WAS_ACTIVE=1; fi
if service_is_active "$BOT_SERVICE"; then BOT_WAS_ACTIVE=1; fi

printf '%s\n' 'Kanit Paneli güncelleme planı'
printf '%s\n' "Kaynak kod: $SOURCE_ROOT"
printf '%s\n' "Hedef: $DEST (yalnız app dizini atomik değiştirilecek)"
printf '%s\n' "Web servisi: $(status_label "$WEB_WAS_ACTIVE"); bot servisi: $(status_label "$BOT_WAS_ACTIVE")"
printf '%s\n' 'Korunacak: .env, data/panel.db, .venv, görseller, telegram_gorseller, sertifika ve config dosyaları.'
printf '%s\n' 'Dokunulmayacak: Plesk nginx/apache2, kanit-ip-proxy, HTTPS yapılandırması, güvenlik duvarı, zamanlayıcılar.'
if (( REQ_UPGRADE )); then
    printf '%s\n' 'Bağımlılık: requirements.txt sürüm yükseltmesi içeriyor; uygulama değişiminden ÖNCE .venv içinde pip install çalışacak:'
    grep '^SURUM_YUKSELTME' <<<"$REQ_DIFF_OUT" | sed 's/^SURUM_YUKSELTME /   /'
elif (( REQ_CHANGED )); then
    printf '%s\n' 'Bağımlılık: requirements.txt yalnız biçimsel değişmiş (sürümler aynı); pip kurulumu yapılmayacak, dosya güncellenecek.'
else
    printf '%s\n' 'Bağımlılık beyanı aynı; pip kurulumu yapılmayacak, yalnız salt denetim pip check çalışacak.'
fi
if (( ${#UNITS_TO_SYNC[@]} )); then
    printf '%s\n' "Servis birim dosyaları güncellenecek (yedek alınır, daemon-reload): $UNITS_LIST"
else
    printf '%s\n' 'Servis birim dosyaları güncel; dokunulmayacak.'
fi

if (( DRY_RUN )); then
    if (( ! WEB_WAS_ACTIVE )); then
        printf '%s\n' 'UYARI: Web servisi pasif; gerçek işlem sağlık denetimi yapamayacağı için başlamaz.'
    fi
    for unit in "${UNITS_TO_SYNC[@]}"; do
        printf 'Birim farkı (%s):\n' "$unit"
        if [[ -f "$UNIT_DIR/$unit" ]]; then
            diff -u "$UNIT_DIR/$unit" "$SOURCE_ROOT/deploy/$unit" | sed 's/^/   /' || true
        else
            printf '   (kurulu birim yok; yeni dosya kopyalanacak)\n'
        fi
    done
    if (( REQ_UPGRADE )); then
        TMP_PIP_DRY="$(mktemp /tmp/kanit-update-pipdry.XXXXXX)"
        chmod 600 "$TMP_PIP_DRY"
        # pip --dry-run çözümler, indirir ama kurmaz; venv değişmez.
        if "${PIP_CMD[@]}" install --dry-run --require-virtualenv --no-input --disable-pip-version-check -r "$SOURCE_ROOT/requirements.txt" >"$TMP_PIP_DRY" 2>&1; then
            printf '%s\n' 'pip çözümleme denemesi (--dry-run): TAMAM; sürümler PyPI/önbellekten çözülebiliyor.'
        else
            printf '%s\n' 'UYARI: pip çözümleme denemesi (--dry-run) başarısız; gerçek güncelleme pip adımında duracak ve eski sürümleri geri kuracaktır. Son satırlar:'
            tail -n 5 "$TMP_PIP_DRY" | sed 's/^/   /'
        fi
        rm -f -- "${TMP_PIP_DRY:?}"
    fi
    printf '%s\n' 'DRY-RUN_TAMAM: Yalnız okuma yapıldı; hiçbir dosya, veritabanı veya servis değiştirilmedi.'
    exit 0
fi

# Sağlık denetimi zorunludur; web önceden kapalı ise kapalı durumunu bozmamak
# için onu başlatmayız ve başarılı güncelleme iddia etmeyiz.
if (( ! WEB_WAS_ACTIVE )); then
    pause_update 30 "kanit-web.service güncelleme öncesinde aktif değil; kapalı servisi otomatik başlatmadan /saglik doğrulanamaz."
fi

TMP_IMPORT_LOG="$(mktemp /tmp/kanit-update-import.XXXXXX)"
TMP_PIP_LOG="$(mktemp /tmp/kanit-update-pip.XXXXXX)"
PREFLIGHT_DATA="$(mktemp -d /tmp/kanit-update-preflight.XXXXXX)"
chmod 600 "$TMP_IMPORT_LOG" "$TMP_PIP_LOG"
chmod 700 "$PREFLIGHT_DATA"
cleanup_preflight() {
    rm -f -- "${TMP_IMPORT_LOG:?}" "${TMP_PIP_LOG:?}" 2>/dev/null || true
    if [[ -n "${PREFLIGHT_DATA:-}" && -d "$PREFLIGHT_DATA" ]]; then rm -rf -- "${PREFLIGHT_DATA:?}" 2>/dev/null || true; fi
}

# pip check salt denetimdir; paket indirmez/değiştirmez. Hata çıktısı, olası
# sır içermesine karşı terminale değil özel geçici günlüğe yönlendirilir.
if ! "${PIP_CMD[@]}" check >"$TMP_PIP_LOG" 2>&1; then
    cleanup_preflight
    pause_update 21 "venv bağımlılık denetimi (pip check) başarısız. Pip otomatik çalıştırılmadı."
fi

# Kaynak paketi /root altında olabileceğinden bu salt-okunur import denetimi
# root bağlamında yapılır. Gerçek .env okunmaz; kanonik, sır içermeyen test
# ortamı ve geçici bir SESSION_SECRET kullanılır. PANEL_VERI olarak canlı data
# dizini DEĞİL geçici bir dizin verilir: settings/gorsel import anında dizin
# oluşturur, canlı data altında root sahipli dizin kalmasın.
if ! env -i \
    "HOME=$DEST" "PATH=$DEST/.venv/bin:/usr/bin:/bin" "PYTHONPATH=$SOURCE_ROOT" PYTHONDONTWRITEBYTECODE=1 \
    "PANEL_VERI=$PREFLIGHT_DATA" DINLE=127.0.0.1 PORT=18080 HTTPS=1 TRUST_PROXY=1 \
    "SESSION_SECRET=$PREFLIGHT_SECRET" \
    "$VENV_PY" -c 'import flask, waitress, openpyxl, PIL, requests, dotenv; import app.settings, app.db, app.panel, app.bot; print("IMPORT_OK")' \
    >"$TMP_IMPORT_LOG" 2>&1; then
    cleanup_preflight
    pause_update 22 "Kaynak temel bağımlılık/import denetiminden geçmedi; canlı dosya değiştirilmedi."
fi
cleanup_preflight

# Bundan sonraki her hata için kod geri alınır ve güncelleme öncesi aktif olan
# servisler tekrar başlatılır. SQLite asla otomatik geri yüklenmez.
STAMP="$(date -u +%Y%m%dT%H%M%SZ)-$$"
BACKUP_DIR="$BACKUP_ROOT/$STAMP"
STAGE_DIR=""
OLD_APP="$DEST/.app.before-$STAMP"
TEMP_SNAPSHOT="$DATA_DIR/.kanit-update-snapshot-$STAMP.db"
SNAPSHOT_HELPER="$DATA_DIR/.kanit-update-support-$STAMP.py"
MIGRATION_LOG=""
HEALTH_BODY=""
UPDATE_CHANGED=0
SERVICES_STOPPED=0
REQ_INSTALLED=0
UNITS_CHANGED=0

# DB ve olası WAL/SHM yan dosyalarının sahipliğini yalnız karşılaştırmak üzere
# kaydeder; içeriklerine dokunmaz.
declare -A DB_OWNER_BEFORE=()
record_db_owners() {
    local item
    for item in "$DB_FILE" "$DB_FILE-wal" "$DB_FILE-shm"; do
        if [[ -e "$item" ]]; then
            DB_OWNER_BEFORE["$item"]="$(stat -c '%u:%g' -- "$item")"
        fi
    done
}
verify_db_owners() {
    local item current
    for item in "${!DB_OWNER_BEFORE[@]}"; do
        # Yan dosya eşzamanlı checkpoint ile kalkmış olabilir; varlığını sürdürürse
        # sahibinin değişmediğini zorunlu kıl. Ana DB her zaman bulunmalıdır.
        if [[ -e "$item" ]]; then
            current="$(stat -c '%u:%g' -- "$item")"
            [[ "$current" == "${DB_OWNER_BEFORE[$item]}" ]] || return 1
        elif [[ "$item" == "$DB_FILE" ]]; then
            return 1
        fi
    done
    return 0
}

ENV_HASH_BEFORE="$(sha256sum -- "$ENV_FILE" | awk '{print $1}')"
ENV_META_BEFORE="$(stat -c '%a:%u:%g' -- "$ENV_FILE")"
assert_env_unchanged() {
    local now_hash now_meta
    now_hash="$(sha256sum -- "$ENV_FILE" | awk '{print $1}')"
    now_meta="$(stat -c '%a:%u:%g' -- "$ENV_FILE")"
    [[ "$now_hash" == "$ENV_HASH_BEFORE" && "$now_meta" == "$ENV_META_BEFORE" ]]
}

cleanup_temporary() {
    rm -f -- "${TEMP_SNAPSHOT:-}" "${SNAPSHOT_HELPER:-}" "${HEALTH_BODY:-}" 2>/dev/null || true
    # Snapshot WAL başlığıyla açılmış olsaydı kalabilecek yan dosyalar (data/ kökünde artık bırakmayız).
    if [[ -n "${TEMP_SNAPSHOT:-}" ]]; then rm -f -- "$TEMP_SNAPSHOT-wal" "$TEMP_SNAPSHOT-shm" 2>/dev/null || true; fi
    if [[ -n "${STAGE_DIR:-}" && -d "$STAGE_DIR" ]]; then
        rm -rf -- "${STAGE_DIR:?}" 2>/dev/null || true
    fi
}

restore_units() {
    local unit
    for unit in "${UNITS_TO_SYNC[@]}"; do
        if [[ -f "$BACKUP_DIR/units.before/$unit" ]]; then
            install -m 644 -o root -g root "$BACKUP_DIR/units.before/$unit" "$UNIT_DIR/$unit" || echo "UYARI: $unit eski birimi geri konamadı." >&2
        else
            rm -f -- "${UNIT_DIR:?}/${unit:?}"
        fi
    done
    "$SYSTEMCTL" daemon-reload >/dev/null 2>&1 || true
}

# pip root olarak çalışır; kurulan dosyalar servis hesabınca okunabilmelidir. Önce dener, gerekirse izinleri düzeltir.
venv_okunabilir_yap() {
    local probe='import PIL.Image, flask, waitress, openpyxl, requests, dotenv'
    if runuser -u "$SERVICE_USER" -- "$VENV_PY" -c "$probe" >/dev/null 2>&1; then return 0; fi
    chmod -R u+rwX,go+rX "$DEST/.venv/lib" "$DEST/.venv/bin" 2>/dev/null || true
    runuser -u "$SERVICE_USER" -- "$VENV_PY" -c "$probe" >/dev/null 2>&1
}

restore_requirements() {
    if [[ -f "$BACKUP_DIR/requirements.before" ]]; then
        echo 'Eski bağımlılık sürümleri geri kuruluyor (pip).' >&2
        # Betik umask 077 ile çalışır; pip'in yazdığı dosyalar kanit hesabınca okunabilmeli (umask 022).
        if ! ( umask 022 && "${PIP_CMD[@]}" install --require-virtualenv --no-input --disable-pip-version-check -r "$BACKUP_DIR/requirements.before" ) >>"$BACKUP_DIR/pip-rollback.log" 2>&1; then
            echo "UYARI: Eski bağımlılık sürümleri geri kurulamadı; günlük: $BACKUP_DIR/pip-rollback.log (elle: $VENV_PY -m pip install -r $BACKUP_DIR/requirements.before)" >&2
        fi
        venv_okunabilir_yap || echo "UYARI: venv dosyaları $SERVICE_USER tarafından okunamıyor; elle: chmod -R u+rwX,go+rX $DEST/.venv" >&2
        install -m 644 -o root -g root "$BACKUP_DIR/requirements.before" "$DEST/requirements.txt" || true
    fi
}

rollback_and_restore() {
    local code="$1"
    local reason="$2"
    trap - ERR INT TERM
    set +e
    echo "GÜNCELLEME_HATASI [$code]: $reason" >&2
    # Sağlık denetiminden sonraki bir hata halinde yeni kod web/bot belleğinde
    # çalışıyor olabilir. Eski app'i taşımadan önce yalnız başlangıçta aktif
    # olan süreçleri durdururuz; başlangıçta kapalı bot asla başlatılmaz.
    if (( SERVICES_STOPPED )); then
        if (( WEB_WAS_ACTIVE )); then
            "$SYSTEMCTL" stop "$WEB_SERVICE" >/dev/null 2>&1 || true
        fi
        if (( BOT_WAS_ACTIVE )); then
            "$SYSTEMCTL" stop "$BOT_SERVICE" >/dev/null 2>&1 || true
        fi
    fi
    if (( UPDATE_CHANGED )) && [[ -d "$OLD_APP" ]]; then
        echo 'Uygulama kodu eski sürüme geri alınıyor.' >&2
        if [[ -d "$DEST/app" ]]; then
            if ! mv -T -- "$DEST/app" "$BACKUP_DIR/failed-app"; then
                rm -rf -- "${DEST:?}/app"
            fi
        fi
        if ! mv -T -- "$OLD_APP" "$DEST/app"; then
            echo 'KRİTİK: Eski app dizini otomatik geri taşınamadı; root yedeğini kullanın.' >&2
        fi
    fi
    if (( REQ_INSTALLED )); then restore_requirements; fi
    if (( UNITS_CHANGED )); then
        echo 'Servis birim dosyaları eski hâline alınıyor.' >&2
        restore_units
    fi
    if (( SERVICES_STOPPED )); then
        if (( WEB_WAS_ACTIVE )); then
            "$SYSTEMCTL" start "$WEB_SERVICE" >/dev/null 2>&1 || echo 'UYARI: Eski web servisi otomatik başlatılamadı.' >&2
        fi
        if (( BOT_WAS_ACTIVE )); then
            "$SYSTEMCTL" start "$BOT_SERVICE" >/dev/null 2>&1 || echo 'UYARI: Eski bot servisi otomatik başlatılamadı.' >&2
        fi
    fi
    cleanup_temporary
    if [[ -n "${BACKUP_DIR:-}" && -d "$BACKUP_DIR" ]]; then
        echo "Yedek/geri dönüş notu: $BACKUP_DIR/GERI_DONUS_NOTU.txt" >&2
    fi
    echo 'SQLite otomatik geri yüklenmedi; yeni kayıt kaybını önlemek için yalnız root, bakımda ve bilinçli kararla yedekteki panel.db dosyasını kullanmalıdır.' >&2
    exit "$code"
}

on_unexpected_error() {
    # shellcheck disable=SC2317  # trap ile dolaylı çağrılır
    local code="$?"
    # shellcheck disable=SC2317
    rollback_and_restore "$code" 'Beklenmeyen işlem hatası.'
}
trap on_unexpected_error ERR
trap 'rollback_and_restore 130 "İşlem kullanıcı tarafından kesildi."' INT
trap 'rollback_and_restore 143 "İşlem sonlandırma sinyali aldı."' TERM

umask 077
if ! install -d -m 700 -o root -g root "$BACKUP_ROOT"; then
    rollback_and_restore 31 'Özel yedek kökü oluşturulamadı.'
fi
if [[ -e "$BACKUP_DIR" ]] || ! install -d -m 700 -o root -g root "$BACKUP_DIR"; then
    rollback_and_restore 31 'Bu güncelleme için özel yedek dizini oluşturulamadı.'
fi
if ! cp -a -- "$DEST/app" "$BACKUP_DIR/sourceapp"; then
    rollback_and_restore 31 'Eski app kaynak yedeği alınamadı.'
fi
if ! cp --preserve=mode,ownership,timestamps -- "$ENV_FILE" "$BACKUP_DIR/.env.before" || \
   ! chown root:root "$BACKUP_DIR/.env.before" || ! chmod 600 "$BACKUP_DIR/.env.before"; then
    rollback_and_restore 31 '.env özel yedeği alınamadı.'
fi
if ! cp -p -- "$DEST/requirements.txt" "$BACKUP_DIR/requirements.before" || ! chmod 600 "$BACKUP_DIR/requirements.before"; then
    rollback_and_restore 31 'requirements.txt yedeği alınamadı.'
fi
if (( ${#UNITS_TO_SYNC[@]} )); then
    install -d -m 700 "$BACKUP_DIR/units.before" || rollback_and_restore 31 'Birim yedek dizini oluşturulamadı.'
    for unit in "${UNITS_TO_SYNC[@]}"; do
        if [[ -f "$UNIT_DIR/$unit" ]] && ! cp -p -- "$UNIT_DIR/$unit" "$BACKUP_DIR/units.before/$unit"; then
            rollback_and_restore 31 "Mevcut $unit birim yedeği alınamadı."
        fi
    done
fi
cat >"$BACKUP_DIR/GERI_DONUS_NOTU.txt" <<EOF
Bu dizin, $STAMP güncellemesinden önce root tarafından oluşturulmuştur.
sourceapp eski uygulama kodudur; .env.before özel ortam yedeğidir; panel.db SQLite backup API ile tutarlı snapshot'tır;
requirements.before eski bağımlılık beyanıdır (pip-install.log varsa pip bu güncellemede çalışmıştır);
units.before/ varsa /etc/systemd/system'deki eski birim dosyalarıdır.
Hata halinde bu betik eski app kodunu, eski bağımlılık sürümlerini, eski birimleri ve önce aktif servisleri geri getirir; panel.db otomatik geri yüklenmez.
Yeni kayıtları kaybetme riskini kabul ediyorsanız yalnız root bakımında servisleri durdurup $BACKUP_DIR/panel.db dosyasını $DB_FILE yerine elle geri yükleyin; önce mevcut DB'nin ayrıca yedeğini alın.
EOF
chmod 600 "$BACKUP_DIR/GERI_DONUS_NOTU.txt"

record_db_owners
# Kaynak paket /root altında olabileceğinden yardımcıyı yalnız snapshot süresi
# için kanit'in erişebildiği data dizinine kopyalarız. Bu geçici dosya silinir.
if ! install -m 644 -o root -g root "$HELPER" "$SNAPSHOT_HELPER"; then
    rollback_and_restore 32 'SQLite snapshot yardımcısı geçici olarak hazırlanamadı.'
fi
if ! runuser -u "$SERVICE_USER" -- /usr/bin/python3 "$SNAPSHOT_HELPER" sqlite-backup \
    --source "$DB_FILE" --destination "$TEMP_SNAPSHOT" >/dev/null; then
    rollback_and_restore 32 "$SERVICE_USER hesabıyla salt-okunur SQLite online snapshot alınamadı."
fi
if ! verify_db_owners; then
    rollback_and_restore 32 'Kaynak SQLite dosyasının veya yan dosyasının sahipliği beklenmedik biçimde değişti.'
fi
if ! mv -T -- "$TEMP_SNAPSHOT" "$BACKUP_DIR/panel.db" || \
   ! chown root:root "$BACKUP_DIR/panel.db" || ! chmod 600 "$BACKUP_DIR/panel.db"; then
    rollback_and_restore 32 'SQLite snapshot özel yedek alanına taşınamadı.'
fi
rm -f -- "$TEMP_SNAPSHOT-wal" "$TEMP_SNAPSHOT-shm" 2>/dev/null || true
rm -f -- "${SNAPSHOT_HELPER:?}"

# Yalnız güncelleme öncesinde aktif olan servisler durdurulur.
SERVICES_STOPPED=1
if (( BOT_WAS_ACTIVE )) && ! "$SYSTEMCTL" stop "$BOT_SERVICE"; then
    rollback_and_restore 33 'Aktif bot servisi güvenli biçimde durdurulamadı.'
fi
if (( WEB_WAS_ACTIVE )) && ! "$SYSTEMCTL" stop "$WEB_SERVICE"; then
    rollback_and_restore 33 'Aktif web servisi güvenli biçimde durdurulamadı.'
fi

# Bağımlılık sürüm yükseltmesi: servisler kapalıyken, uygulama kodu değişmeden ÖNCE.
# Başarısızsa eski sürümler geri kurulur ve eski app dokunulmamış kalır.
if (( REQ_UPGRADE )); then
    REQ_INSTALLED=1
    # umask 077 altında pip'in yazdığı dosyalar yalnız root okuyabilirdi (servis açılamazdı); kurulum umask 022 ile.
    if ! ( umask 022 && "${PIP_CMD[@]}" install --require-virtualenv --no-input --disable-pip-version-check -r "$SOURCE_ROOT/requirements.txt" ) >"$BACKUP_DIR/pip-install.log" 2>&1; then
        rollback_and_restore 37 "pip ile bağımlılık sürüm yükseltmesi başarısız (günlük: $BACKUP_DIR/pip-install.log); uygulama kodu değiştirilmedi."
    fi
    if ! "${PIP_CMD[@]}" check >>"$BACKUP_DIR/pip-install.log" 2>&1; then
        rollback_and_restore 37 "Yükseltme sonrası pip check başarısız (günlük: $BACKUP_DIR/pip-install.log)."
    fi
    if ! venv_okunabilir_yap; then
        rollback_and_restore 38 "Yükseltilen paketler $SERVICE_USER hesabınca içe aktarılamadı (izin/kurulum sorunu); eski sürümler geri kuruldu."
    fi
    chmod 600 "$BACKUP_DIR/pip-install.log" || true
fi
if (( REQ_CHANGED )) && ! install -m 644 -o root -g root "$SOURCE_ROOT/requirements.txt" "$DEST/requirements.txt"; then
    rollback_and_restore 37 'Yeni requirements.txt hedefe yazılamadı.'
fi

# Birim dosyaları: yeni app başlatılmadan önce kurulur ve daemon-reload yapılır.
if (( ${#UNITS_TO_SYNC[@]} )); then
    UNITS_CHANGED=1
    for unit in "${UNITS_TO_SYNC[@]}"; do
        if ! install -m 644 -o root -g root "$SOURCE_ROOT/deploy/$unit" "$UNIT_DIR/$unit"; then
            rollback_and_restore 38 "$unit birim dosyası yazılamadı."
        fi
        if command -v systemd-analyze >/dev/null 2>&1 && ! systemd-analyze verify "$UNIT_DIR/$unit" >"$BACKUP_DIR/unit-verify.log" 2>&1; then
            rollback_and_restore 38 "$unit systemd-analyze verify denetiminden geçmedi (günlük: $BACKUP_DIR/unit-verify.log)."
        fi
    done
    if ! "$SYSTEMCTL" daemon-reload; then
        rollback_and_restore 38 'systemctl daemon-reload başarısız.'
    fi
fi

# Yeni app hedef dosya sistemi üzerinde aşamalıdır; böylece mv -T ile atomik
# dizin değişimi yapılır. data/.env/.venv/deploy/service/sertifika/config yoktur.
if ! STAGE_DIR="$(mktemp -d "$DEST/.kanit-update-stage-$STAMP.XXXXXX")"; then
    rollback_and_restore 34 'Yeni app için aşama dizini oluşturulamadı.'
fi
if ! cp -a -- "$SOURCE_ROOT/app" "$STAGE_DIR/app"; then
    rollback_and_restore 34 'Yeni app kaynakları aşama dizinine kopyalanamadı.'
fi
# Paketlenmiş bytecode taşınmaz; kaynak erişimi root:root, dizin 0755, dosya
# 0644 olur. Böylece kanit servisi kodu okuyabilir, değiştiremez.
find "$STAGE_DIR/app" -type d -name __pycache__ -prune -exec rm -rf -- {} +
find "$STAGE_DIR/app" -type f -name '*.pyc' -delete
if ! chown -R root:root "$STAGE_DIR/app" || \
   ! find "$STAGE_DIR/app" -type d -exec chmod 755 {} + || \
   ! find "$STAGE_DIR/app" -type f -exec chmod 644 {} +; then
    rollback_and_restore 34 'Aşama app izinleri güvenli biçimde ayarlanamadı.'
fi
if [[ -e "$OLD_APP" ]]; then
    rollback_and_restore 34 'Eski app için geçici ad beklenmedik biçimde zaten var.'
fi
UPDATE_CHANGED=1
if ! mv -T -- "$DEST/app" "$OLD_APP"; then
    rollback_and_restore 35 'Eski app dizini atomik değişim için taşınamadı.'
fi
if ! mv -T -- "$STAGE_DIR/app" "$DEST/app"; then
    rollback_and_restore 35 'Yeni app dizini atomik olarak yerine alınamadı.'
fi
if ! assert_env_unchanged; then
    rollback_and_restore 36 '.env içeriği veya izinleri işlem sırasında değişti; kod geri alındı.'
fi

# Gerçek .env yalnız kanit hesabınca okunur. Kod eklemeli/idempotent migration'ı
# app.db/settings üzerinden açar; token/parola stdout'a yönlendirilmez.
# Çalışma dizini DEST'tir: "python -c" sys.path[0] olarak cwd'yi eklediği için app paketi kesinlikle
# yeni kurulan $DEST/app'ten gelir (kaynak paketin açıldığı dizinden değil).
MIGRATION_LOG="$BACKUP_DIR/migration-private.log"
if ! (cd "$DEST" && runuser -u "$SERVICE_USER" -- env -i \
    "HOME=$DEST" "PATH=$DEST/.venv/bin:/usr/bin:/bin" "PYTHONPATH=$DEST" "PANEL_VERI=$DATA_DIR" PYTHONDONTWRITEBYTECODE=1 \
    "$VENV_PY" -c '
from app.settings import AYAR
from app import db, bot
conn = db.baglan(AYAR["DB"])
try:
    # Ağ çağrısı veya görsel dizini oluşturma olmadan botun additive şemasını
    # kur. KanitBot örneği oluşturulmaz; gorseller/telegram_gorseller korunur.
    conn.executescript(bot.BOT_SEMA)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(tg_giden)")}
    for name, kind in (("replace_message_id", "INTEGER"), ("job_key", "TEXT")):
        if name not in columns:
            conn.execute("ALTER TABLE tg_giden ADD COLUMN " + name + " " + kind)
    required = {
        "kayitlar", "panel_kullanicilari", "denetim", "ice_aktarim", "ayarlar",
        "islem_sonuclari", "tg_kullanicilar", "kategoriler", "tg_oturumlar",
        "tg_gelen", "tg_durum", "arsiv_dosyalar", "bildirimler", "yorumlar",
        "tg_girisler", "tg_tema", "mesaj_bildirimleri", "schema_migrations",
        "projeler", "proje_kategorileri", "kategori_sorular", "donusum_isleri",
        "tg_giden", "tg_indirilen", "tg_donusum_cache",
    }
    existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type=\047table\047")}
    if not required.issubset(existing):
        raise RuntimeError("Additive şema nesnesi eksik")
    check = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if str(check).lower() != "ok":
        raise RuntimeError("SQLite bütünlük denetimi başarısız")
finally:
    conn.close()
print("MIGRATION_OK")
' >"$MIGRATION_LOG" 2>&1); then
    rollback_and_restore 40 'Yeni uygulamanın additive veritabanı migration denetimi başarısız oldu.'
fi
if ! assert_env_unchanged; then
    rollback_and_restore 41 '.env içeriği veya izinleri migration sırasında değişti; kod geri alındı.'
fi

# Web önceden aktifti; sadece onu tekrar başlatıp loopback sağlık kontrolü yaparız.
if ! "$SYSTEMCTL" start "$WEB_SERVICE"; then
    rollback_and_restore 42 'Yeni web servisi başlatılamadı.'
fi
HEALTH_BODY="$(mktemp /tmp/kanit-update-health.XXXXXX)"
chmod 600 "$HEALTH_BODY"
HEALTH_OK=0
for ((attempt=1; attempt<=12; attempt++)); do
    if curl --fail --silent --show-error --noproxy '*' --max-time 3 --output "$HEALTH_BODY" "$HEALTH_URL" >/dev/null 2>&1 && \
       [[ "$(cat -- "$HEALTH_BODY")" == 'OK' ]]; then
        HEALTH_OK=1
        break
    fi
    sleep 1
done
if (( ! HEALTH_OK )); then
    rollback_and_restore 43 "$HEALTH_URL sınırlandırılmış denemelerde başarılı olmadı."
fi

# Bot yalnızca güncelleme öncesinde aktif ise geri başlatılır; kullanıcı kapalı
# bıraktıysa bu betik onu kesinlikle otomatik başlatmaz.
BOT_UYARI=0
if (( BOT_WAS_ACTIVE )); then
    if ! "$SYSTEMCTL" start "$BOT_SERVICE"; then
        rollback_and_restore 44 'Önceden aktif bot servisi yeniden başlatılamadı.'
    fi
    # Type=simple 'start' hemen döner; sertleştirilmiş birimle açılamayan bot saniyeler sonra düşer. Geri alma yok
    # (web sağlıklı), yalnız görünür uyarı; çıkış kodu değişmez.
    sleep "${KANIT_BOT_BEKLE:-5}"
    if ! service_is_active "$BOT_SERVICE"; then BOT_UYARI=1; fi
fi
if ! assert_env_unchanged; then
    rollback_and_restore 45 '.env içeriği veya izinleri son denetimde değişti; kod geri alındı.'
fi

# Eski kod canlı yedekte zaten sourceapp olarak tutulur; geçici kopya kaldırılır.
rm -rf -- "${OLD_APP:?}" "${STAGE_DIR:?}" 2>/dev/null || true
cleanup_temporary
UPDATE_CHANGED=0
trap - ERR INT TERM
printf '%s\n' "GÜNCELLEME_TAMAM: /saglik yalnız loopback $HEALTH_URL üzerinden doğrulandı."
printf '%s\n' "Özel yedek: $BACKUP_DIR"
if (( REQ_UPGRADE )); then printf '%s\n' "Bağımlılık yükseltmesi uygulandı (günlük: $BACKUP_DIR/pip-install.log; eski beyan: requirements.before)."; fi
if (( UNITS_CHANGED )); then printf '%s\n' "Servis birim dosyaları güncellendi: $UNITS_LIST (eskileri: $BACKUP_DIR/units.before/)"; fi
if (( BOT_UYARI )); then
    printf 'UYARI: kanit-bot açılamadı veya başladıktan sonra durdu (web sağlıklı, güncelleme geri alınmadı). Bakın: journalctl -u kanit-bot -n 50; birim satırlarını şüpheliyse: systemctl cat kanit-bot\n'
fi
# data altında kanit dışı sahipli dosya kaldıysa sessiz bozulma olmasın diye uyar (ön kontrol artık data'ya yazmaz).
if find "$DATA_DIR" ! -user "$SERVICE_USER" -print -quit 2>/dev/null | grep -q .; then
    printf 'UYARI: %s altında %s dışı sahipli dosya/dizin var; düzeltin: systemctl stop kanit-web kanit-bot; chown -R %s:%s %s; systemctl start kanit-web kanit-bot\n' "$DATA_DIR" "$SERVICE_USER" "$SERVICE_USER" "$SERVICE_USER" "$DATA_DIR"
    find "$DATA_DIR" ! -user "$SERVICE_USER" 2>/dev/null | head -n 5 | sed 's/^/   /'
fi
printf '%s\n' 'Dış HTTPS erişimi doğrulanmadı veya iddia edilmedi; Plesk/Nginx/HTTPS yapılandırması değiştirilmedi.'
exit 0
