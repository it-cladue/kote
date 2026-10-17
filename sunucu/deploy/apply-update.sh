#!/usr/bin/env bash
# Kanıt Paneli 2.0 -> 2.1 güvenli uygulama-kodu güncellemesi.
# Bu betik ZIP açmaz, paket indirmez, pip/apt ile kurulum yapmaz ve Plesk/Nginx/HTTPS
# yapılandırmasına dokunmaz. Kaynak kök, bu deploy dizininin bir üstüdür.
set -Eeuo pipefail
IFS=$'\n\t'
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH

readonly DEST=/opt/kanit-paneli
readonly DATA_DIR=/opt/kanit-paneli/data
readonly ENV_FILE=/opt/kanit-paneli/.env
readonly DB_FILE=/opt/kanit-paneli/data/panel.db
readonly VENV_PY=/opt/kanit-paneli/.venv/bin/python
readonly WEB_SERVICE=kanit-web.service
readonly BOT_SERVICE=kanit-bot.service
readonly BACKUP_ROOT=/var/backups/kanit-paneli
readonly HEALTH_URL=http://127.0.0.1:18080/saglik
readonly PREFLIGHT_SECRET='kanit-update-preflight-only-0123456789abcdef0123456789abcdef'

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SOURCE_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)"
HELPER="$SCRIPT_DIR/update-support.py"
DRY_RUN=0

usage() {
    cat <<'USAGE'
Kullanım: sudo bash deploy/apply-update.sh [--dry-run]

Kaynak, bu betiğin bulunduğu deploy dizininin üst köküdür. Hedef sabittir:
/opt/kanit-paneli. --dry-run yalnız okuyarak ön koşulları, uyumluluğu ve servis
aktifliğini raporlar; yedek, dosya, veritabanı veya servis değişikliği yapmaz.
USAGE
}

case "${1:-}" in
    '') ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
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
    echo "Otomatik pip/apt kurulumu ve yapılandırma değişikliği yapılmadı." >&2
    exit "$code"
}

need_command() {
    command -v "$1" >/dev/null 2>&1 || fatal 11 "Gerekli komut bulunamadı: $1"
}

service_is_active() {
    systemctl is-active --quiet "$1"
}

status_label() {
    if [[ "$1" == 1 ]]; then printf 'aktif'; else printf 'pasif'; fi
}

if [[ ${EUID} -ne 0 ]]; then
    fatal 10 "Bu betik root olarak çalıştırılmalı (sudo bash deploy/apply-update.sh)."
fi

for bin in python3 runuser systemctl curl sha256sum stat cmp cp mv find chown chmod install mktemp awk sleep cat rm date env; do
    need_command "$bin"
done

[[ -f "$HELPER" && ! -L "$HELPER" && -r "$HELPER" ]] || \
    fatal 11 "update-support.py kaynak pakette okunabilir normal dosya değil. ZIP'i önce kullanıcı olarak açın."
[[ "$SOURCE_ROOT" != "$DEST" ]] || \
    fatal 11 "Kaynak paket /opt/kanit-paneli olamaz; açılmış 2.1 paketin deploy/apply-update.sh betiğini çalıştırın."

# Yalnız okuyan kaynak derleme denetimi: __pycache__ oluşturmaz.
if ! python3 "$HELPER" source-check --root "$SOURCE_ROOT" >/dev/null; then
    fatal 12 "Kaynak app/ veya requirements.txt doğrulanamadı; hiçbir canlı dosya değiştirilmedi."
fi

[[ -d "$DEST" && ! -L "$DEST" ]] || fatal 13 "Hedef /opt/kanit-paneli normal dizin değil."
[[ -d "$DEST/app" && ! -L "$DEST/app" ]] || fatal 13 "Mevcut app dizini normal dizin değil."
[[ -f "$DEST/requirements.txt" && ! -L "$DEST/requirements.txt" && -r "$DEST/requirements.txt" ]] || \
    fatal 13 "Hedef requirements.txt okunamıyor."
[[ -x "$VENV_PY" ]] || fatal 13 ".venv/bin/python çalıştırılabilir değil."
[[ -d "$DATA_DIR" && ! -L "$DATA_DIR" ]] || fatal 13 "PANEL_VERI dizini beklenen normal dizin değil."
[[ -f "$DB_FILE" && ! -L "$DB_FILE" ]] || fatal 13 "Beklenen SQLite dosyası data/panel.db bulunamadı."
id kanit >/dev/null 2>&1 || fatal 13 "kanit servis hesabı bulunamadı."
KANIT_GID="$(id -g kanit)"

# .env asla shell source edilmez. Yardımcı yalnız beklenen ağ/veri ayarlarını
# denetler ve hiçbir değer yazdırmaz.
if ! python3 "$HELPER" env-check --env "$ENV_FILE" --owner 0 --group "$KANIT_GID" >/dev/null; then
    fatal 14 ".env özel izin/sahiplik veya PANEL_VERI/DINLE/PORT/HTTPS/TRUST_PROXY uyumluluğunu sağlamıyor."
fi
if ! runuser -u kanit -- test -r "$ENV_FILE"; then
    fatal 14 "kanit hesabı .env dosyasını okuyamıyor; servis başlatılması güvenli değil."
fi
if ! runuser -u kanit -- test -r "$DB_FILE" -a -w "$DATA_DIR"; then
    fatal 14 "kanit hesabı SQLite kaynağını okuyamıyor veya geçici snapshot dizinine yazamıyor."
fi
if ! runuser -u kanit -- test -r "$DEST/app/__init__.py" -a -x "$DEST/app"; then
    fatal 14 "kanit hesabı mevcut app kodunu okuyamıyor."
fi
if ! runuser -u kanit -- "$VENV_PY" -c 'import sys; assert sys.version_info >= (3, 8)' >/dev/null 2>&1; then
    fatal 14 ".venv Python kanit hesabıyla çalışma denetiminden geçmedi."
fi

# Yeni paket bağımlılık beyanını değiştirmişse bu betik bilinçli olarak pip
# çalıştırmaz. Operatör önce kontrollü bağımlılık incelemesi yapmalıdır.
if ! cmp -s "$SOURCE_ROOT/requirements.txt" "$DEST/requirements.txt"; then
    pause_update 20 "requirements.txt değişmiş. Bu betik pip çalıştırmaz; bağımlılıkları elle doğrulayıp onaylı bakımda güncelleyin."
fi

WEB_WAS_ACTIVE=0
BOT_WAS_ACTIVE=0
if service_is_active "$WEB_SERVICE"; then WEB_WAS_ACTIVE=1; fi
if service_is_active "$BOT_SERVICE"; then BOT_WAS_ACTIVE=1; fi

printf '%s\n' 'Kanit Paneli 2.1 güncelleme planı'
printf '%s\n' "Kaynak kod: $SOURCE_ROOT"
printf '%s\n' "Hedef: $DEST (yalnız app dizini atomik değiştirilecek)"
printf '%s\n' "Web servisi: $(status_label "$WEB_WAS_ACTIVE"); bot servisi: $(status_label "$BOT_WAS_ACTIVE")"
printf '%s\n' 'Korunacak: .env, data/panel.db, .venv, görseller, telegram_gorseller, sertifika, config ve service dosyaları.'
printf '%s\n' 'Dokunulmayacak: Plesk nginx/apache2, kanit-ip-https, HTTPS yapılandırması, güvenlik duvarı, cron/zamanlama ve sertifika yenilemesi.'
printf '%s\n' 'Bağımlılık beyanı aynı; pip kurulumu yapılmayacak, yalnız salt denetim pip check çalışacak.'

if (( DRY_RUN )); then
    if (( ! WEB_WAS_ACTIVE )); then
        printf '%s\n' 'UYARI: Web servisi pasif; gerçek işlem sağlık denetimi yapamayacağı için başlamaz.'
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
chmod 600 "$TMP_IMPORT_LOG" "$TMP_PIP_LOG"
cleanup_preflight_logs() {
    rm -f -- "${TMP_IMPORT_LOG:-}" "${TMP_PIP_LOG:-}" 2>/dev/null || true
}

# pip check salt denetimdir; paket indirmez/değiştirmez. Hata çıktısı, olası
# sır içermesine karşı terminale değil özel geçici günlüğe yönlendirilir.
if ! "$VENV_PY" -m pip check >"$TMP_PIP_LOG" 2>&1; then
    cleanup_preflight_logs
    pause_update 21 "venv bağımlılık denetimi (pip check) başarısız. Pip otomatik çalıştırılmadı."
fi

# Kaynak paketi /root altında olabileceğinden bu salt-okunur import denetimi
# root bağlamında yapılır. Gerçek .env okunmaz; kanonik, sır içermeyen test
# ortamı ve geçici bir SESSION_SECRET kullanılır.
if ! env -i \
    "HOME=$DEST" "PATH=$DEST/.venv/bin:/usr/bin:/bin" "PYTHONPATH=$SOURCE_ROOT" PYTHONDONTWRITEBYTECODE=1 \
    "PANEL_VERI=$DATA_DIR" DINLE=127.0.0.1 PORT=18080 HTTPS=1 TRUST_PROXY=1 \
    "SESSION_SECRET=$PREFLIGHT_SECRET" \
    "$VENV_PY" -c 'import flask, waitress, openpyxl, PIL, requests, dotenv; import app.settings, app.db, app.panel, app.bot; print("IMPORT_OK")' \
    >"$TMP_IMPORT_LOG" 2>&1; then
    cleanup_preflight_logs
    pause_update 22 "Kaynak temel bağımlılık/import denetiminden geçmedi; canlı dosya değiştirilmedi."
fi
cleanup_preflight_logs

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
    if [[ -n "${STAGE_DIR:-}" && -d "$STAGE_DIR" ]]; then
        rm -rf -- "$STAGE_DIR" 2>/dev/null || true
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
            systemctl stop "$WEB_SERVICE" >/dev/null 2>&1 || true
        fi
        if (( BOT_WAS_ACTIVE )); then
            systemctl stop "$BOT_SERVICE" >/dev/null 2>&1 || true
        fi
    fi
    if (( UPDATE_CHANGED )) && [[ -d "$OLD_APP" ]]; then
        echo 'Uygulama kodu eski sürüme geri alınıyor.' >&2
        if [[ -d "$DEST/app" ]]; then
            if ! mv -T -- "$DEST/app" "$BACKUP_DIR/failed-app"; then
                rm -rf -- "$DEST/app"
            fi
        fi
        if ! mv -T -- "$OLD_APP" "$DEST/app"; then
            echo 'KRİTİK: Eski app dizini otomatik geri taşınamadı; root yedeğini kullanın.' >&2
        fi
    fi
    if (( SERVICES_STOPPED )); then
        if (( WEB_WAS_ACTIVE )); then
            systemctl start "$WEB_SERVICE" >/dev/null 2>&1 || echo 'UYARI: Eski web servisi otomatik başlatılamadı.' >&2
        fi
        if (( BOT_WAS_ACTIVE )); then
            systemctl start "$BOT_SERVICE" >/dev/null 2>&1 || echo 'UYARI: Eski bot servisi otomatik başlatılamadı.' >&2
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
    local code="$?"
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
cat >"$BACKUP_DIR/GERI_DONUS_NOTU.txt" <<EOF
Bu dizin, $STAMP güncellemesinden önce root tarafından oluşturulmuştur.
sourceapp eski uygulama kodudur; .env.before özel ortam yedeğidir; panel.db SQLite backup API ile tutarlı snapshot'tır.
Hata halinde bu betik eski app kodunu ve önce aktif servisleri geri getirir; panel.db otomatik geri yüklenmez.
Yeni kayıtları kaybetme riskini kabul ediyorsanız yalnız root bakımında servisleri durdurup $BACKUP_DIR/panel.db dosyasını $DB_FILE yerine elle geri yükleyin; önce mevcut DB'nin ayrıca yedeğini alın.
EOF
chmod 600 "$BACKUP_DIR/GERI_DONUS_NOTU.txt"

record_db_owners
# Kaynak paket /root altında olabileceğinden yardımcıyı yalnız snapshot süresi
# için kanit'in erişebildiği data dizinine kopyalarız. Bu geçici dosya silinir.
if ! install -m 644 -o root -g root "$HELPER" "$SNAPSHOT_HELPER"; then
    rollback_and_restore 32 'SQLite snapshot yardımcısı geçici olarak hazırlanamadı.'
fi
if ! runuser -u kanit -- /usr/bin/python3 "$SNAPSHOT_HELPER" sqlite-backup \
    --source "$DB_FILE" --destination "$TEMP_SNAPSHOT" >/dev/null; then
    rollback_and_restore 32 'kanit hesabıyla salt-okunur SQLite online snapshot alınamadı.'
fi
if ! verify_db_owners; then
    rollback_and_restore 32 'Kaynak SQLite dosyasının veya yan dosyasının sahipliği beklenmedik biçimde değişti.'
fi
if ! mv -T -- "$TEMP_SNAPSHOT" "$BACKUP_DIR/panel.db" || \
   ! chown root:root "$BACKUP_DIR/panel.db" || ! chmod 600 "$BACKUP_DIR/panel.db"; then
    rollback_and_restore 32 'SQLite snapshot özel yedek alanına taşınamadı.'
fi
rm -f -- "$SNAPSHOT_HELPER"

# Yalnız güncelleme öncesinde aktif olan servisler durdurulur.
SERVICES_STOPPED=1
if (( BOT_WAS_ACTIVE )) && ! systemctl stop "$BOT_SERVICE"; then
    rollback_and_restore 33 'Aktif bot servisi güvenli biçimde durdurulamadı.'
fi
if (( WEB_WAS_ACTIVE )) && ! systemctl stop "$WEB_SERVICE"; then
    rollback_and_restore 33 'Aktif web servisi güvenli biçimde durdurulamadı.'
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
MIGRATION_LOG="$BACKUP_DIR/migration-private.log"
if ! runuser -u kanit -- env -i \
    "HOME=$DEST" "PATH=$DEST/.venv/bin:/usr/bin:/bin" "PYTHONPATH=$DEST" \
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
' >"$MIGRATION_LOG" 2>&1; then
    rollback_and_restore 40 'Yeni uygulamanın additive veritabanı migration denetimi başarısız oldu.'
fi
if ! assert_env_unchanged; then
    rollback_and_restore 41 '.env içeriği veya izinleri migration sırasında değişti; kod geri alındı.'
fi

# Web önceden aktifti; sadece onu tekrar başlatıp loopback sağlık kontrolü yaparız.
if ! systemctl start "$WEB_SERVICE"; then
    rollback_and_restore 42 'Yeni web servisi başlatılamadı.'
fi
HEALTH_BODY="$(mktemp /tmp/kanit-update-health.XXXXXX)"
chmod 600 "$HEALTH_BODY"
HEALTH_OK=0
for ((attempt=1; attempt<=12; attempt++)); do
    if curl --fail --silent --show-error --max-time 3 --output "$HEALTH_BODY" "$HEALTH_URL" >/dev/null 2>&1 && \
       [[ "$(cat -- "$HEALTH_BODY")" == 'OK' ]]; then
        HEALTH_OK=1
        break
    fi
    sleep 1
done
if (( ! HEALTH_OK )); then
    rollback_and_restore 43 '127.0.0.1:18080/saglik sınırlandırılmış denemelerde başarılı olmadı.'
fi

# Bot yalnızca güncelleme öncesinde aktif ise geri başlatılır; kullanıcı kapalı
# bıraktıysa bu betik onu kesinlikle otomatik başlatmaz.
if (( BOT_WAS_ACTIVE )) && ! systemctl start "$BOT_SERVICE"; then
    rollback_and_restore 44 'Önceden aktif bot servisi yeniden başlatılamadı.'
fi
if ! assert_env_unchanged; then
    rollback_and_restore 45 '.env içeriği veya izinleri son denetimde değişti; kod geri alındı.'
fi

# Eski kod canlı yedekte zaten sourceapp olarak tutulur; geçici kopya kaldırılır.
rm -rf -- "$OLD_APP" "$STAGE_DIR" 2>/dev/null || true
cleanup_temporary
UPDATE_CHANGED=0
trap - ERR INT TERM
printf '%s\n' "GÜNCELLEME_TAMAM: /saglik yalnız loopback $HEALTH_URL üzerinden doğrulandı."
printf '%s\n' "Özel yedek: $BACKUP_DIR"
printf '%s\n' 'Dış HTTPS erişimi doğrulanmadı veya iddia edilmedi; Plesk/Nginx/HTTPS yapılandırması değiştirilmedi.'
exit 0
