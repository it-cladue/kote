import importlib.util
from pathlib import Path
import pytest
from dotenv import dotenv_values

spec=importlib.util.spec_from_file_location('private_settings',Path(__file__).parents[1]/'deploy/apply-private-settings.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)

def test_private_patch_preserves_https_and_other_settings(tmp_path):
    path=tmp_path/'private.env'
    values={'TELEGRAM_TOKEN':'12345678'+':'+'x'*35,'GYAZO_TOKEN':'fake-upload-key','BOT_PASSWORD':'test-password','ADMIN_PASSWORD':'other-test-password','ADMIN_IDS':'99,99,100','MAX_DENEME':'3','GYAZO_BAKIM':'1'}
    path.write_text('\n'.join(k+'='+v for k,v in values.items()));path.chmod(0o600)
    patch=helper.parse_patch(path);assert patch['ADMIN_IDS']=='99,100'
    merged=tmp_path/'merged.env';merged.write_text(helper.merge('HTTPS=1\nTRUST_PROXY=1\nPORT=18080\nSESSION_SECRET=keep-test-session\nGYAZO_TOKEN=old\n',patch))
    result=dotenv_values(merged,interpolate=False)
    assert result['HTTPS']=='1' and result['TRUST_PROXY']=='1' and result['PORT']=='18080' and result['SESSION_SECRET']=='keep-test-session'
    assert result['GYAZO_TOKEN']=='fake-upload-key' and merged.read_text().count('GYAZO_TOKEN=')==1
    path.chmod(0o644)
    with pytest.raises(ValueError):helper.parse_patch(path)
