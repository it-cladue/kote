# -*- coding: utf-8 -*-
"""2.2 genel panel testleri: menü, BETA projesi, parola kuralı, CLI, hata sayfaları, ana sayfa kapsamı."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db, katalog, kullanicilar
from test_web import web, seed, login, csrf

ROOT = Path(__file__).resolve().parents[1]


def account(config, name, role, password='Test-Password-123!'):
    kullanicilar.ekle(config, name, role, password)
    kullanicilar.guncelle(config, name, sifre_degistir=0)


def test_menu_links_per_role_and_version(web):
    client, config = web
    account(config, 'ofonly', 'OF:oku,kt')
    assert client.get('/saglik').headers['X-Kanit-Paneli'] == '2.2.0'
    login(client)
    html = client.get('/').data.decode()
    for text in ('>Ana sayfa<', 'href="/kayitlar"', 'href="/disa-aktar"', '>Çıktı<', '>Kanıt Kontrolü<', '>Bildirimler<', '>İşlem Geçmişi<',
                 'Yönetim', 'href="/yonetim/katalog"', 'href="/yonetim/kullanicilar"', 'href="/bot"', 'href="/arsiv"',
                 'data-menu-dugme', 'id="zil"', 'id="bildirim-kutu"', 'Tümünü okundu say', 'Süperadmin', 'stil.css?v=2.2.3', 'panel.js?v=2.2.3'):
        assert text in html, text
    assert '<title>Ana sayfa — Kanıt Paneli</title>' in html
    assert '<title>Kayıtlar — Kanıt Paneli</title>' in client.get('/kayitlar').data.decode()
    assert 'aria-current="page"' in client.get('/denetim').data.decode()
    client.post('/cikis', data={'csrf': csrf(client)}); login(client, 'ofonly')
    html = client.get('/').data.decode()
    assert 'href="/disa-aktar"' in html and '>Kayıtlar<' in html
    for text in ('href="/yonetim/katalog"', 'href="/yonetim/kullanicilar"', 'href="/bot"', 'href="/arsiv"', 'Yönetim <span'):
        assert text not in html, text
    assert 'kullanici-rol">Admin<' in html


def test_beta_project_seeded_once_and_admin_choice_respected(tmp_path):
    conn = db.baglan(str(tmp_path / 'fresh.db'))
    try:
        beta = katalog.get_project(conn, 'BETA')
        assert beta and beta['aktif'] == 1 and beta['color'] == '#FFA500' and beta['label'] == 'BETA'
        codes = [p['code'] for p in katalog.list_projects(conn, active_only=True)]
        assert codes[:6] == ['PP', 'PA', 'OF', 'HI', 'VI', 'GA'] and 'BETA' in codes
        assert katalog.get_category(conn, 'ark')['projects'].count('BETA') == 1
        # Admin BETA'yı pasife alır ve renk değiştirirse sonraki bağlantılar geri getirmez.
        katalog.save_project(conn, 'BETA', 'Beta deneme', '#123456', False, actor='super', expected_revision=beta['revision'])
    finally:
        conn.close()
    conn = db.baglan(str(tmp_path / 'fresh.db'))
    try:
        katalog.ensure_schema(conn)
        again = katalog.get_project(conn, 'BETA')
        assert again['aktif'] == 0 and again['color'] == '#123456' and again['label'] == 'Beta deneme'
    finally:
        conn.close()


def test_beta_added_to_existing_21_database_without_touching_rows(tmp_path):
    """2.1 kurulumunu taklit et: katalog geçişi yapılmış ama BETA yok."""
    path = str(tmp_path / 'eski.db')
    conn = db.baglan(path)
    try:
        pa = katalog.get_project(conn, 'PA')
        katalog.save_project(conn, 'PA', 'PA özel ad', '#ABCDEF', True, actor='super', expected_revision=pa['revision'])
        with db.transaction(conn):
            conn.execute("DELETE FROM proje_kategorileri WHERE proje_code='BETA'")
            conn.execute("DELETE FROM projeler WHERE code='BETA'")
            conn.execute("DELETE FROM schema_migrations WHERE name=?", (katalog.BETA_MIGRATION_NAME,))
        assert conn.execute("SELECT COUNT(*) FROM projeler WHERE code='BETA'").fetchone()[0] == 0
    finally:
        conn.close()
    conn = db.baglan(path)
    try:
        beta = katalog.get_project(conn, 'BETA')
        assert beta and beta['aktif'] == 1 and beta['color'] == '#FFA500'
        assert katalog.get_project(conn, 'PA')['label'] == 'PA özel ad'
        assert conn.execute('SELECT COUNT(*) FROM schema_migrations WHERE name=?', (katalog.BETA_MIGRATION_NAME,)).fetchone()[0] == 1
    finally:
        conn.close()


def test_beta_visible_in_ui_and_bot_config(web):
    client, config = web
    login(client)
    for url in ('/yonetim/kullanicilar', '/disa-aktar', '/'):
        assert 'value="BETA"' in client.get(url).data.decode() or 'BETA' in client.get(url).data.decode(), url
    assert 'value="BETA"' in client.get('/yonetim/kullanicilar').data.decode()
    assert '#FFA500' in client.get('/').data.decode()
    from app import bot_yonetim
    assert 'BETA' in bot_yonetim.config(config)['Projeler']


def test_password_rule_is_eight_characters(web):
    client, config = web
    with pytest.raises(ValueError):
        kullanicilar.ekle(config, 'kisa', 'OF:oku', 'Abc1234')
    kullanicilar.ekle(config, 'sekiz', 'OF:oku', 'Abc12345')
    with pytest.raises(ValueError):
        kullanicilar.guncelle(config, 'sekiz', sifre='1234567')
    login(client)
    assert client.post('/sifre', data={'csrf': csrf(client), 'eski': 'Test-Password-123!', 'yeni': 'kisa123', 'yeni2': 'kisa123'}).status_code == 200
    assert client.post('/sifre', data={'csrf': csrf(client), 'eski': 'Test-Password-123!', 'yeni': 'tam8kara', 'yeni2': 'tam8kara'}).status_code == 302
    assert kullanicilar.dogrula(config, 'testadmin', 'tam8kara')[0]
    assert 'minlength="8"' in client.get('/sifre').data.decode()
    assert 'minlength="8"' in client.get('/yonetim/kullanicilar').data.decode()
    assert client.post('/yonetim/kullanicilar', data={'csrf': csrf(client), 'islem': 'ekle', 'ad': 'yeni8', 'rol': 'admin', 'projeler': 'OF', 'sifre': 'Sekiz123'}).status_code == 302
    assert kullanicilar.bul(config, 'yeni8')['sifre_degistir'] == 1


def _cli(tmp_path, *args, env=None):
    environment = dict(os.environ, PANEL_VERI=str(tmp_path / 'veri'), GYAZO_WORKER='0')
    environment.update(env or {})
    return subprocess.run([sys.executable, '-m', 'app.cli', *args], cwd=str(ROOT), env=environment, capture_output=True, text=True, timeout=120)


def test_cli_password_env_and_kalici_flag(tmp_path):
    result = _cli(tmp_path, 'admin-ekle', 'cliadmin', '--password-env', 'KANIT_PW', env={'KANIT_PW': 'telecc123'})
    assert result.returncode == 0, result.stderr
    config = {'DB': str(tmp_path / 'veri' / 'panel.db')}
    user = kullanicilar.bul(config, 'cliadmin')
    assert user['sifre_degistir'] == 0 and user['yetki'] == 'admin' and kullanicilar.dogrula(config, 'cliadmin', 'telecc123')[0]
    result = _cli(tmp_path, 'sifre-sifirla', 'cliadmin', '--password-env', 'KANIT_PW', env={'KANIT_PW': 'gecici-sifre-1'})
    assert result.returncode == 0, result.stderr
    assert kullanicilar.bul(config, 'cliadmin')['sifre_degistir'] == 1
    result = _cli(tmp_path, 'sifre-sifirla', 'cliadmin', '--password-env', 'KANIT_PW', '--kalici', env={'KANIT_PW': 'telecc123'})
    assert result.returncode == 0 and 'kalıcı' in result.stdout, result.stderr
    user = kullanicilar.bul(config, 'cliadmin')
    assert user['sifre_degistir'] == 0 and user['aktif'] == 1 and kullanicilar.dogrula(config, 'cliadmin', 'telecc123')[0]
    short = _cli(tmp_path, 'sifre-sifirla', 'cliadmin', '--password-env', 'KANIT_PW', env={'KANIT_PW': 'kisa'})
    assert short.returncode != 0 and 'en az 8' in (short.stderr + short.stdout)
    empty = _cli(tmp_path, 'sifre-sifirla', 'cliadmin', '--password-env', 'YOK_DEGISKEN')
    assert empty.returncode != 0


def test_error_pages_have_back_link_and_json_negotiation(web):
    client, config = web
    login(client)
    page = client.get('/boyle-bir-sayfa-yok')
    assert page.status_code == 404 and 'Geri dön' in page.data.decode() and 'data-geri' in page.data.decode() and 'Sayfa bulunamadı' in page.data.decode()
    missing = client.get('/kayit/999999', headers={'Accept': 'text/html,application/xhtml+xml'})
    assert missing.status_code == 404 and 'bulunamad' in missing.data.decode().lower()
    api = client.get('/kayit/999999', headers={'Accept': '*/*'})
    assert api.status_code == 404 and api.is_json and api.json['ok'] is False and 'bulunamad' in api.json['hata'].lower()
    posted = client.post('/kayit/999999/kt', data={'csrf': csrf(client)}, headers={'X-CSRF': csrf(client)})
    assert posted.status_code == 404 and posted.is_json
    forbidden = client.get('/yonetim/katalog', headers={'Accept': '*/*'}, environ_base={'REMOTE_ADDR': '127.0.0.1'})
    assert forbidden.status_code in (200, 403)
    bad = client.post('/bildirimler/okundu', data={'hepsi': '1'}, headers={'Accept': '*/*'})
    assert bad.status_code == 400 and bad.is_json and bad.json['hata'] == 'Geçersiz CSRF. Sayfayı yenileyin.'
    bad_page = client.post('/bildirimler/okundu', data={'hepsi': '1'}, headers={'Accept': 'text/html'})
    assert bad_page.status_code == 400 and 'Geçersiz CSRF' in bad_page.data.decode() and 'Geri dön' in bad_page.data.decode()


def test_server_error_logs_reference_and_shows_friendly_page(web, monkeypatch):
    from app import panel
    client, config = web
    login(client)
    def explode():
        raise RuntimeError('beklenmeyen test hatasi')
    monkeypatch.setattr(panel, 'durum_bilgisi', explode)
    monkeypatch.setitem(panel.app.config, 'PROPAGATE_EXCEPTIONS', False)
    response = client.get('/')
    html = response.data.decode()
    assert response.status_code == 500 and 'Beklenmeyen hata, kayıt no ' in html and 'Geri dön' in html and 'beklenmeyen test hatasi' not in html
    conn = db.baglan(config['DB'])
    row = conn.execute("SELECT yeni,sonuc FROM denetim WHERE islem='sunucu_hata' ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert row and row['sonuc'] == 'hata' and 'RuntimeError' in row['yeni']
    api = client.get('/', headers={'Accept': '*/*', 'X-Requested-With': 'XMLHttpRequest'})
    assert api.status_code == 500 and api.is_json and api.json['kayit_no']


def test_home_kpis_and_recent_activity_are_permission_scoped(web):
    client, config = web
    account(config, 'ofonly', 'OF:oku,kt')
    account(config, 'paonly', 'PA:oku,kt')
    of = seed(config); pa = seed(config, 'PA', 'tg:9:9:9', picture=False)
    conn = db.baglan(config['DB'])
    with db.transaction(conn):
        conn.execute("UPDATE kayitlar SET kt=1,kt_zaman=?,kt_kim='testadmin' WHERE id=?", (db.simdi(), pa))
        conn.execute("INSERT INTO kayitlar(anahtar,proje,personel,kaynak,tarih,guncelleme) VALUES('tg:9:9:10','PA','PA_PRIVATE_PERSON','telegram',?,?)", (db.simdi(), db.simdi()))
        db.denetim_yaz(conn, 'testadmin', 'onayla', 'PA', 'tg:9:9:9', 0, 1)
        db.denetim_yaz(conn, 'testadmin', 'duzenle', 'OF', 'tg:1:2:3', yeni='OF_VISIBLE_CHANGE')
        from app import discussion
        discussion.add(conn, of, 'testadmin', 'Bu kanıt doğru mu?', 'ofonly')
        discussion.add(conn, pa, 'testadmin', 'PA sorusu', 'paonly')
    conn.close()
    login(client, 'ofonly')
    html = client.get('/').data.decode()
    assert '"PA":' not in html and 'value="PA"' not in html and 'PA_PRIVATE_PERSON' not in html and 'tg:9:9:9' not in html
    assert 'OF_VISIBLE_CHANGE' not in html  # ayrıntı değil, yalnız özet satırı
    assert 'Kaydı düzenledi' in html and 'Kaydı onayladı' not in html
    assert '<b data-kpi="bekleyen">1</b>' in html
    assert 'Bana yöneltilmiş açık soru' in html and '<b>1</b><span>Bana yöneltilmiş' in html
    assert '<b>0</b><span>Bugün onaylanan' in html and '<b>1</b><span>Bugün eklenen' in html
    client.post('/cikis', data={'csrf': csrf(client)}); login(client)
    html = client.get('/').data.decode()
    assert '<b data-kpi="bekleyen">2</b>' in html and '<b>1</b><span>Bugün onaylanan' in html and '<b>3</b><span>Bugün eklenen' in html
    assert 'Kaydı onayladı' in html and '<b>0</b><span>Bana yöneltilmiş' in html
    conn = db.baglan(config['DB'])
    with db.transaction(conn):
        discussion.add(conn, of, 'ofonly', 'Evet doğru', '', conn.execute("SELECT id FROM yorumlar WHERE alici='ofonly'").fetchone()[0])
    conn.close()
    client.post('/cikis', data={'csrf': csrf(client)}); login(client, 'ofonly')
    assert '<b>0</b><span>Bana yöneltilmiş' in client.get('/').data.decode()


def test_other_pages_render_with_new_header_pattern(web):
    client, config = web
    login(client); kid = seed(config)
    conn = db.baglan(config['DB']); conn.execute("UPDATE kayitlar SET ekleyen_id='77'"); conn.execute("INSERT INTO tg_kullanicilar(id,username) VALUES('77','tester')"); conn.close()
    for url, title in [('/bildirimler', 'Bildirimler — Kanıt Paneli'), ('/denetim', 'İşlem Geçmişi — Kanıt Paneli'), ('/arsiv', 'Görsel arşivi — Kanıt Paneli'),
                       ('/bot', 'Bot yönetimi — Kanıt Paneli'), ('/bot/kullanici/77', 'Telegram kullanıcısı 77 — Kanıt Paneli'), ('/telegram/kullanici/77/kanitlar', 'Telegram kayıt profili — Kanıt Paneli'),
                       ('/excel-kontrol', 'Kanıt Kontrolü — Kanıt Paneli'), ('/disa-aktar', 'Çıktı (Excel) — Kanıt Paneli'), ('/yonetim/katalog', 'Proje ve kategoriler — Kanıt Paneli'),
                       ('/yonetim/kullanicilar', 'Kullanıcılar — Kanıt Paneli'), ('/sifre', 'Şifre değiştir — Kanıt Paneli')]:
        response = client.get(url)
        html = response.data.decode()
        assert response.status_code == 200, url
        assert '<title>' + title + '</title>' in html, url
        assert 'class="ust-etiket"' in html and '<h1' in html, url
        assert 'onclick=' not in html, url
    giris = client.get('/giris').data.decode()
    assert 'Kanıt Paneli' in giris and 'giris-kutu' in giris and 'stil.css?v=2.2.3' in giris
