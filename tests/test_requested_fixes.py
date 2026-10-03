import asyncio
import httpx
import pytest
from test_integration import make_runtime


def test_final_killing_hits_never_respawn_and_finale_emitted_once(tmp_path, config):
    rt = make_runtime(tmp_path, config)
    asyncio.run(rt.admin_action('sim_final_boss'))
    rt.sim_boss.active.hp = 1
    asyncio.run(rt.admin_action('sim_hit', {'emote': 'Kappa'}))
    for _ in range(8):
        asyncio.run(rt.admin_action('sim_hit', {'emote': 'Kappa'}))
    asyncio.run(rt.admin_action('sim_medipack'))
    asyncio.run(rt.admin_action('sim_rider_boost'))
    assert rt.sim_boss.active is None
    assert len([e for e in rt.events_since(0) if e['type'] == 'CHALLENGE_FINALE']) == 1
    assert rt.db.count('fights') == 0
    asyncio.run(rt.admin_action('sim_boss'))
    assert rt.sim_boss.active is not None


@pytest.mark.parametrize('before,after,mark,kind', [(1019.9,1020.1,1020,'small'),(1099.9,1100.1,1100,'major')])
def test_live_bosses_continue_after_target(tmp_path,config,before,after,mark,kind):
    rt=make_runtime(tmp_path,config)
    rt.challenge.set_total(before)
    rt.challenge.state['last_live_distance']=0
    rt.challenge.state['session_id']='ride'
    asyncio.run(rt.process_telemetry({'distance':after-before,'session_id':'ride'}))
    assert rt.boss.active.km_mark==mark
    assert rt.boss.active.boss_type==kind
    assert not rt.boss.active.final_boss
    assert rt.challenge.snapshot()['total_km']==after
    assert rt.challenge.snapshot()['percent']==100
    assert not [e for e in rt.events_since(0) if e['type']=='FINAL_BOSS_READY']


def test_sim_and_next_marks_above_target(tmp_path,config):
    rt=make_runtime(tmp_path,config)
    rt.challenge.set_total(1123)
    asyncio.run(rt.admin_action('simulation_start'))
    state=rt.overlay_state()['challenge']
    assert state['total_km']==1123
    assert state['next_10_km']==1130 and state['next_100_km']==1200
    assert rt.boss_warning(1139.5)['mark_km']==1140
    assert asyncio.run(rt.admin_action('sim_progress',{'percent':112.3}))['challenge']['total_km']==1123


def test_helix_network_error_identifies_failed_operation(tmp_path,config):
    rt=make_runtime(tmp_path,config)
    rt.twitch.token='test'
    async def offline(*args,**kwargs):
        raise httpx.ConnectError('')
    rt.twitch._request=offline
    with pytest.raises(RuntimeError,match='Twitch API GET /channel_points/custom_rewards'):
        asyncio.run(rt.twitch.list_custom_rewards())


def test_websocket_sends_fight_state_before_projectiles(tmp_path,config):
    from fastapi.testclient import TestClient
    from backend.app import create_app
    rt=make_runtime(tmp_path,config)
    # The test app only needs the existing empty static directory.
    asyncio.run(rt.admin_action('sim_boss'))
    asyncio.run(rt.admin_action('sim_hit',{'emote':'Kappa'}))
    with TestClient(create_app(rt)) as client:
        with client.websocket_connect('/ws') as ws:
            first=ws.receive_json()
            assert first['type']=='state'
            fight_id=first['payload']['boss']['fight_id']
            for _ in range(10):
                message=ws.receive_json()
                if message['type']=='event' and message['payload']['type']=='BOSS_HIT':
                    assert message['payload']['payload']['fight_id']==fight_id
                    break
            else:
                pytest.fail('Missing hit event')
