import asyncio
from backend.boss import BossEngine
from test_integration import make_runtime


def events(rt,kind):
    return [e for e in rt.events_since(0) if e['type']==kind]


def test_target_reached_spawns_final_boss_without_premature_fireworks(tmp_path,config):
    rt=make_runtime(tmp_path,config)
    rt.challenge.set_total(999.9)
    rt.challenge.state['last_live_distance']=0
    rt.challenge.state['session_id']='ride'
    asyncio.run(rt.process_telemetry({'distance':.2,'session_id':'ride'}))
    assert rt.boss.active.final_boss
    assert rt.boss.active.km_mark==1000
    assert rt.boss.active.boss_type=='major'
    assert events(rt,'FINAL_BOSS_READY')
    assert not events(rt,'GOAL_COMPLETE')
    assert not events(rt,'CHALLENGE_FINALE')
    summary=rt.boss.finish('won')
    rt._emit_boss_end(summary)
    assert len(events(rt,'CHALLENGE_FINALE'))==1
    rt._emit_boss_end(summary)
    assert len(events(rt,'CHALLENGE_FINALE'))==1
    assert rt.challenge.state['final_boss_victory']==summary['fight_id']


def test_final_boss_does_not_depend_on_distance_interval(services,config):
    challenge,_=services
    config['boss']['interval_km']=30
    config['boss']['major_interval_km']=120
    challenge.set_total(999.9)
    challenge.state['last_live_distance']=0
    challenge.state['session_id']='x'
    r=challenge.ingest_live_distance(.2,session_id='x')
    final=[t for t in r.triggers if t['type']=='BOSS_SPAWN']
    assert len(final)==1 and final[0]['mark_km']==1000 and final[0]['boss_type']=='major'


def test_final_boss_waits_for_previous_fight(tmp_path,config):
    rt=make_runtime(tmp_path,config)
    rt.boss.start('small',980,1)
    asyncio.run(rt._handle_distance_trigger({'type':'BOSS_SPAWN','mark_km':1000,'boss_type':'major','dedupe_key':'boss:1000'}))
    assert rt.boss.active.km_mark==980
    rt._emit_boss_end(rt.boss.finish('lost'))
    assert rt.boss.active.final_boss and rt.boss.active.km_mark==1000
    assert not events(rt,'CHALLENGE_FINALE')


def test_finale_simulation_and_loss_are_isolated(tmp_path,config):
    rt=make_runtime(tmp_path,config)
    asyncio.run(rt.admin_action('sim_final_boss'))
    assert rt.sim_boss.active.final_boss
    asyncio.run(rt.admin_action('sim_boss_end',{'result':'lost'}))
    assert not events(rt,'CHALLENGE_FINALE')
    asyncio.run(rt.admin_action('sim_final_boss'))
    asyncio.run(rt.admin_action('sim_boss_end',{'result':'won'}))
    assert events(rt,'CHALLENGE_FINALE')
    assert not rt.challenge.state.get('final_boss_victory')
    assert rt.db.count('fights')==0


def test_normal_win_never_starts_final_fireworks(tmp_path,config):
    rt=make_runtime(tmp_path,config)
    rt.boss.start('major',100,1)
    rt._emit_boss_end(rt.boss.finish('won'))
    assert events(rt,'BOSS_DEFEATED') and not events(rt,'CHALLENGE_FINALE')
