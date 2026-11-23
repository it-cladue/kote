#!/usr/bin/env bash
# Kanıt Paneli — ufw güvenlik duvarı (İSTEĞE BAĞLI; Plesk sunucusunda dikkatle). --uygula olmadan yalnız PLAN yazar.
#
#   bash deploy/setup-firewall.sh                 # mevcut durum + plan; hiçbir şeyi değiştirmez
#   bash deploy/setup-firewall.sh --uygula        # kuralları uygular ve ufw'yi etkinleştirir (önce SSH izni)
#   seçenekler: --plesk         8443/8880 (Plesk paneli) dışa AÇIK kalır (varsayılan: kapalı; lisans bitmiş)
#               --posta-kapat   25/465/587/993/995/110/143 posta portları KAPATILIR (varsayılan: açık; yayındaki posta bozulmasın)
#               --ssh-port N    sshd_config yerine bu SSH portu (birden çok için virgülle: 22,2222)
#
# Kurallar: default deny incoming / allow outgoing; allow SSH (sshd_config'den; yoksa 22) ÖNCE; 80, 443, 18443/tcp;
# 18080/tcp açıkça deny (arka uç zaten 127.0.0.1'de). Uyguladıktan sonra mevcut PuTTY oturumunu KAPATMADAN yeni bir
# oturumla SSH girişini doğrulayın. Alan adı Cloudflare üzerinden yayına girince 18443 kapatılır: ufw delete allow 18443/tcp
# UYARI: Plesk'in kendi güvenlik duvarı (psa-firewall) ya da fail2ban iptables zincirleri varsa ufw ikinci bir yönetici olur;
# betik bunları gösterir, karar sizindir.
set -Eeuo pipefail
IFS=$'\n\t'
SSHD_CONFIG="${KANIT_SSHD_CONFIG:-/etc/ssh/sshd_config}"
SSHD_CONFIG_D="${KANIT_SSHD_CONFIG_D:-/etc/ssh/sshd_config.d}"
UFW="${KANIT_UFW:-ufw}"
if [[ -z "${KANIT_TEST:-}" ]]; then PATH=/usr/sbin:/usr/bin:/sbin:/bin; export PATH; fi

UYGULA=0; PLESK=0; POSTA_KAPAT=0; SSH_SECIM=''
while (( $# )); do
    case "$1" in
        --uygula) UYGULA=1 ;;
        --plesk) PLESK=1 ;;
        --posta-kapat) POSTA_KAPAT=1 ;;
        --ssh-port) shift; SSH_SECIM="${1:-}"; [[ "$SSH_SECIM" =~ ^[0-9]+(,[0-9]+)*$ ]] || { echo 'HATA: --ssh-port sayı (ya da 22,2222) olmalı.' >&2; exit 2; } ;;
        --dry-run) UYGULA=0 ;;
        -h|--help|--yardim) sed -n '2,15p' "$0"; exit 0 ;;
        *) echo "HATA: Bilinmeyen seçenek: $1 (--yardim)" >&2; exit 2 ;;
    esac
    shift
done
fail() { printf 'DUR: %s\n' "$*" >&2; exit 1; }
bilgi() { printf '%s\n' "$*"; }
[[ ${EUID} -eq 0 ]] || fail 'Root oturumu gerekli.'

# SSH portları: --ssh-port > sshd -T (etkin yapılandırma) > sshd_config(.d) Port satırları > 22
ssh_portlari() {
    local portlar=''
    if [[ -n "$SSH_SECIM" ]]; then
        portlar="${SSH_SECIM//,/ }"
    elif [[ -z "${KANIT_TEST:-}" ]] && command -v sshd >/dev/null 2>&1; then
        portlar="$(sshd -T 2>/dev/null | awk '$1=="port"{print $2}' | sort -un | tr '\n' ' ')"
    fi
    if [[ -z "${portlar// /}" ]]; then
        portlar="$(cat "$SSHD_CONFIG" "$SSHD_CONFIG_D"/*.conf 2>/dev/null | sed -E 's/#.*//' | awk 'tolower($1)=="port" && $2 ~ /^[0-9]+$/ {print $2}' | sort -un | tr '\n' ' ')"
    fi
    [[ -n "${portlar// /}" ]] || portlar='22'
    printf '%s' "$portlar" | xargs
}
SSH_PORTLAR="$(ssh_portlari)"
IFS=' ' read -r -a SSH_DIZI <<<"$SSH_PORTLAR"

bilgi '=== Mevcut durum (salt okunur) ==='
if command -v "$UFW" >/dev/null 2>&1; then
    bilgi "ufw: $("$UFW" status 2>/dev/null | head -1 || echo 'durum alınamadı')"
    "$UFW" status numbered 2>/dev/null | sed -n '2,40p' | sed 's/^/   /' || true
else
    bilgi 'ufw: kurulu değil (apt-get install -y ufw)'
fi
if [[ -z "${KANIT_TEST:-}" ]]; then
    if systemctl is-active --quiet psa-firewall 2>/dev/null; then
        bilgi 'UYARI: Plesk güvenlik duvarı (psa-firewall) AKTİF; ufw ile birlikte iki yönetici çakışır. Önce birini seçin.'
    else
        bilgi 'psa-firewall: aktif değil'
    fi
    if command -v iptables >/dev/null 2>&1; then
        F2B="$(iptables -S 2>/dev/null | grep -c '^-N f2b-' || true)"
        bilgi "iptables: INPUT politikası $(iptables -S INPUT 2>/dev/null | head -1 | awk '{print $3}' || echo '?'); fail2ban zinciri: ${F2B:-0} (Plesk fail2ban; ufw ile birlikte çalışır, kurallar INPUT'a eklenir)"
    fi
    if command -v ss >/dev/null 2>&1; then
        bilgi 'Dinleyen TCP portları (ss -lnt):'
        ss -lntH 2>/dev/null | awk '{print $4}' | sed -E 's/.*:([0-9]+)$/\1/' | sort -un | tr '\n' ' ' | sed 's/^/   /'; echo
    fi
fi

# Plan
PLAN=()
for p in "${SSH_DIZI[@]}"; do PLAN+=("allow $p/tcp comment SSH"); done
PLAN+=("allow 80/tcp comment HTTP" "allow 443/tcp comment HTTPS" "allow 18443/tcp comment Kanit-IP-yolu")
if (( PLESK )); then PLAN+=("allow 8443/tcp comment Plesk" "allow 8880/tcp comment Plesk"); fi
if (( ! POSTA_KAPAT )); then
    for p in 25 465 587 993 995 110 143; do PLAN+=("allow $p/tcp comment Posta"); done
fi
PLAN+=("deny 18080/tcp comment Kanit-arka-uc-yalniz-loopback")

bilgi ''
bilgi '=== Plan ==='
bilgi "SSH portu: $SSH_PORTLAR ($( [[ -n "$SSH_SECIM" ]] && echo '--ssh-port' || echo 'sshd yapılandırmasından; yanlışsa --ssh-port N') ) — ÖNCE izin verilir."
bilgi 'ufw default deny incoming'
bilgi 'ufw default allow outgoing'
for r in "${PLAN[@]}"; do bilgi "ufw $r"; done
bilgi 'ufw --force enable'
bilgi ''
if (( PLESK )); then bilgi 'Plesk 8443/8880: AÇIK (--plesk).'; else bilgi 'Plesk 8443/8880: KAPALI (lisans bitmiş; gerekirse --plesk).'; fi
if (( POSTA_KAPAT )); then
    bilgi 'Posta portları: KAPALI (--posta-kapat). /var/qmail/mailnames altında alan adı varsa posta kesilir!'
else
    bilgi 'Posta portları (25/465/587/993/995/110/143): AÇIK bırakıldı — sunucuda Plesk posta alanları var; yayındaki posta bozulmasın. Kapatmak için --posta-kapat.'
fi
bilgi '18080: dışa deny (arka uç yalnız 127.0.0.1); 18443 Cloudflare yolu çalışınca kapatılabilir: ufw delete allow 18443/tcp'

if (( ! UYGULA )); then
    bilgi ''
    bilgi 'PLAN_YAZILDI: hiçbir şey değiştirilmedi. Uygulamak için: bash deploy/setup-firewall.sh --uygula [--plesk] [--posta-kapat]'
    exit 0
fi

command -v "$UFW" >/dev/null 2>&1 || fail 'ufw kurulu değil: apt-get install -y ufw'
bilgi ''
bilgi '=== Uygulanıyor ==='
"$UFW" default deny incoming
"$UFW" default allow outgoing
for r in "${PLAN[@]}"; do
    # shellcheck disable=SC2086
    "$UFW" $r
done
"$UFW" --force enable
"$UFW" status numbered | sed 's/^/   /'
bilgi 'GUVENLIK_DUVARI_TAMAM: ufw etkin. ŞİMDİ bu oturumu kapatmadan YENİ bir PuTTY oturumuyla SSH girişini doğrulayın; girilemiyorsa bu oturumdan: ufw disable'
