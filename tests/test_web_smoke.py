import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.runtime import StreamRuntime
from backend.trainer import FakeTrainerAdapter


def test_pages_and_api_smoke(tmp_path, config):
    root=Path(__file__).resolve().parents[1]
    # Use the real web assets but isolated data/config by cloning minimum runtime root tree via tmp links/copies.
    import shutil
    work=tmp_path/'work';shutil.copytree(root/'web',work/'web');(work/'config').mkdir(parents=True);(work/'data').mkdir()
    (work/'config'/'challenge_config.json').write_text(json.dumps(config),encoding='utf-8')
    (work/'gc_live.json').write_text(json.dumps({'distance':0,'speed':0,'power':0,'heartrate':0,'cadence':0,'timestamp':0}),encoding='utf-8')
    rt=StreamRuntime(root=work,trainer_adapter=FakeTrainerAdapter())
    app=create_app(rt)
    with TestClient(app) as client:
        for url in ['/challenge-overlay','/event-overlay','/dashboard','/admin','/sub-info-overlay','/sub-info-compact-overlay']:
            r=client.get(url);assert r.status_code==200;assert '<html' in r.text.lower()
            if url == '/admin':
                assert 'Mit Twitch anmelden' in r.text
                assert 'Zurückgeben' in r.text
        state=client.get('/api/state');assert state.status_code==200;assert 'challenge' in state.json()
        r=client.post('/api/admin/action',json={'action':'simulation_start','payload':{}});assert r.status_code==200;assert r.json()['simulation'] is True
