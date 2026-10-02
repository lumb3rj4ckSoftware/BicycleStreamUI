import asyncio
import json
from pathlib import Path

from backend.runtime import StreamRuntime
from backend.trainer import FakeTrainerAdapter


def make_runtime(tmp_path, config):
    root=tmp_path
    (root/'config').mkdir();(root/'data').mkdir();(root/'web'/'static').mkdir(parents=True)
    (root/'config'/'challenge_config.json').write_text(json.dumps(config),encoding='utf-8')
    return StreamRuntime(root=root,trainer_adapter=FakeTrainerAdapter())


def test_fake_twitch_gift_raid_and_trainer(tmp_path, config):
    rt=make_runtime(tmp_path,config)
    rt.config['features']['twitch_integration']=True
    rt.trainer.enable()
    asyncio.run(rt.on_twitch_gift({'total':10,'user_name':'GiftGuy'}))
    assert rt.physical.active.kind=='climb'
    assert rt.trainer.adapter.commands[-1] == ('grade',1.0)
    # Finish and process raid.
    rt.physical.tick(now=rt.physical.active.end_at+1)
    asyncio.run(rt.on_twitch_raid({'viewers':73,'from_broadcaster_user_name':'Raider'}))
    assert rt.physical.active.duration_s==73


def test_simulation_does_not_write_boss_stats(tmp_path, config):
    rt=make_runtime(tmp_path,config)
    before={t:rt.db.count(t) for t in ['fights','damage_totals','reward_eligibility']}
    asyncio.run(rt.admin_action('simulation_start'))
    asyncio.run(rt.admin_action('sim_boss',{'boss_type':'small','chatters':3}))
    asyncio.run(rt.admin_action('sim_hit',{'subscriber':True}))
    asyncio.run(rt.admin_action('sim_medipack',{}))
    asyncio.run(rt.admin_action('sim_boss_end',{'result':'won'}))
    after={t:rt.db.count(t) for t in before}
    assert before==after
