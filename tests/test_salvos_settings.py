import asyncio
from unittest.mock import AsyncMock
import pytest
from backend.config import update_config, load_config
from backend.emotes import emotes_from_fragments, ThirdPartyEmoteResolver
from test_integration import make_runtime


def test_repeat_emotes_order_and_single_damage(tmp_path, config):
    rt=make_runtime(tmp_path,config)
    rt.config['features']['twitch_integration']=True
    asyncio.run(rt.admin_action('sim_boss',{'chatters':1}))
    hp=rt.sim_boss.active.hp
    fragments=[{'type':'emote','text':'Kappa','emote':{'id':'25'}} for _ in range(10)]
    asyncio.run(rt.on_twitch_chat({'chatter_user_id':'a','message':{'text':' '.join(['Kappa']*10),'fragments':fragments}}))
    hits=[e for e in rt.events_since(0) if e['type']=='BOSS_HIT']
    assert len(hits[-1]['payload']['emotes'])==10
    assert rt.sim_boss.active.hp==hp-1
    assert rt.sim_boss.active.participants['a']['hits']==1
    assert rt.db.count('damage_totals')==0


def test_provider_duplicates_and_mixed_order():
    r=ThirdPartyEmoteResolver()
    r._add('Dance','https://example/dance.webp','7TV','7')
    r._add('Wave','https://example/wave.gif','BTTV','b')
    fragments=[{'type':'text','text':'Dance Dance'}, {'type':'emote','text':'Kappa','emote':{'id':'25'}}, {'type':'text','text':'Wave Dance'}]
    assert [e['code'] for e in emotes_from_fragments(fragments,r)]==['Dance','Dance','Kappa','Wave','Dance']


def test_sim_hit_native_run(tmp_path,config):
    rt=make_runtime(tmp_path,config)
    asyncio.run(rt.admin_action('sim_hit',{'emote':'Kappa Kappa LUL Kappa','subscriber':True}))
    hit=[e for e in rt.events_since(0) if e['type']=='BOSS_HIT'][-1]['payload']
    assert [e['code'] for e in hit['emotes']]==['Kappa','Kappa','LUL','Kappa']
    assert hit['damage']==2


def test_warning_boundary_restart_and_finished_mark(tmp_path,config):
    rt=make_runtime(tmp_path,config)
    assert rt.boss_warning(19.499) is None
    assert rt.boss_warning(19.5)['remaining_m']==500
    assert rt.boss_warning(19.99)['mark_km']==20
    assert rt.boss_warning(20) is None
    assert rt.boss_warning(99.5)['boss_type']=='major'
    assert rt.boss_warning(1000) is None
    assert rt.boss_warning(19.5,boss_active=True) is None
    rt.challenge.set_total(19.5)
    assert rt.overlay_state()['boss_warning']['mark_km']==20
    rt.challenge.state['triggered_events']=['boss:20']
    assert rt.overlay_state()['boss_warning'] is None
    assert rt.boss_warning(19.5,simulation=True) is not None
    rt.config['features']['boss_battles']=False
    assert rt.boss_warning(19.5,simulation=True) is None


def test_admin_settings_persist_and_apply_next_spawn(tmp_path,config):
    rt=make_runtime(tmp_path,config)
    asyncio.run(rt.admin_action('sim_boss',{'boss_type':'small'}))
    assert rt.sim_boss.active.duration_s==150
    asyncio.run(rt.admin_action('config_patch',{'overlay':{'emote_size_px':100,'emote_speed_percent':70},'boss':{'small_duration_seconds':220,'major_duration_seconds':400}}))
    assert rt.sim_boss.active.duration_s==150
    cfg=load_config(tmp_path/'config'/'challenge_config.json')
    assert cfg['overlay']['emote_size_px']==100
    asyncio.run(rt.admin_action('sim_boss',{'boss_type':'small'}))
    assert rt.sim_boss.active.duration_s==220
    asyncio.run(rt.admin_action('sim_boss',{'boss_type':'major'}))
    assert rt.sim_boss.active.duration_s==400
    assert rt.overlay_state()['sub_challenge_config']['sprint_5_seconds']==30


@pytest.mark.parametrize('patch',[{'overlay':{'emote_size_px':0}}, {'overlay':{'emote_speed_percent':201}}, {'overlay':{'emote_speed_percent':float('nan')}}, {'boss':{'small_duration_seconds':0}}, {'boss':{'major_duration_seconds':float('inf')}}])
def test_invalid_settings_rejected(config,patch):
    with pytest.raises(ValueError):update_config(config,patch)


def test_help_command_lists_all_and_sim_warning_action(tmp_path,config):
    rt=make_runtime(tmp_path,config)
    reply=rt.commands.handle('!october1000','a')
    for command in ['!km','!heute','!plan','!next','!boss','!damage','!topdamage','!october1000']:assert command in reply
    assert len(reply)<500
    before=rt.challenge.snapshot()['total_km']
    result=asyncio.run(rt.admin_action('sim_boss_warning'))
    assert result['boss_warning']['remaining_m']==500
    assert rt.challenge.snapshot()['total_km']==before
