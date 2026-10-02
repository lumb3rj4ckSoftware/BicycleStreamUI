import time
from backend.boss import BossEngine


def test_5000_server_side_hits_stay_reasonable(config, tmp_path):
    # Persistence is intentionally off here: this measures the core counting loop/browser-independent path.
    e=BossEngine(config,None,persist=False)
    config['boss']['small_hp_max']=100000
    config['boss']['small_hp_min']=100000
    config['boss']['small_hp_base']=100000
    e.start('small',20,1,now=100,simulation=True)
    em={'id':'25','url':'x'}
    start=time.perf_counter()
    for i in range(5000):
        e.hit({'user_id':str(i%50),'login':'u','display_name':'U'},subscriber=(i%3==0),emote=em,now=101+i*.001)
    elapsed=time.perf_counter()-start
    assert elapsed < 2.0
    assert e.active is not None
    assert sum(p['hits'] for p in e.active.participants.values())==5000
