import asyncio
from unittest.mock import AsyncMock

from backend.boss import BossEngine
from backend.emotes import ThirdPartyEmoteResolver, emotes_from_fragments
from test_integration import make_runtime


def test_all_emote_providers_and_punctuation():
    resolver = ThirdPartyEmoteResolver()
    resolver._add('Dance', 'https://cdn.example/dance.gif', '7TV', 'a')
    resolver._add('Wave', 'https://cdn.example/wave.gif', 'BTTV', 'b')
    fragments = [{'type':'emote','text':'Kappa','emote':{'id':'25'}}, {'type':'text','text':'Dance! Wave Dance'}]
    found = emotes_from_fragments(fragments, resolver)
    assert [e['provider'] for e in found] == ['Twitch','7TV','BTTV','7TV']
    assert len(emotes_from_fragments([], resolver, 'Dance Wave')) == 2


def test_twenty_monsters_before_repeat(config):
    e = BossEngine(config, None, persist=False)
    ids = []
    for _ in range(20):
        ids.append(e.start('small',20,3,simulation=True)['monster_id'])
        e.finish('lost')
    assert len(set(ids)) == 20
    assert e.hp_for('small',1) == 47
    assert e.hp_for('small',20) == 275
    assert e.hp_for('major',1) == 125
    assert e.hp_for('major',20) == 600


def test_real_chat_in_sim_isolated_and_once_per_message(tmp_path, config):
    rt = make_runtime(tmp_path, config)
    rt.config['features']['twitch_integration'] = True
    rt.twitch.send_chat = AsyncMock(return_value=True)
    asyncio.run(rt.admin_action('sim_boss', {'chatters':1}))
    hp = rt.sim_boss.active.hp
    event = {'chatter_user_id':'alice','chatter_user_name':'Alice','message':{'text':'Kappa LUL', 'fragments':[{'type':'emote','text':'Kappa','emote':{'id':'25'}},{'type':'emote','text':'LUL','emote':{'id':'425618'}}]}}
    asyncio.run(rt.on_twitch_chat(event))
    assert rt.sim_boss.active.hp == hp-1
    hits = [e for e in rt.events_since(0) if e['type']=='BOSS_HIT']
    assert len(hits[-1]['payload']['emotes']) == 2
    assert rt.db.count('damage_totals') == 0
    assert rt.db.count('fights') == 0
    event['message'] = {'text':'!damage'}
    asyncio.run(rt.on_twitch_chat(event))
    assert '[SIM]' in rt.twitch.send_chat.call_args.args[0]
    assert '1 Damage' in rt.twitch.send_chat.call_args.args[0]


def test_local_commands_use_simulated_progress_and_empty_input(tmp_path, config):
    rt = make_runtime(tmp_path, config)
    asyncio.run(rt.admin_action('sim_progress',{'percent':75}))
    result = asyncio.run(rt.admin_action('sim_chat',{'text':'!km'}))
    assert '750.0/1000' in result['reply']
    assert rt.commands.handle('', 'nobody') is None
    assert rt.challenge.snapshot()['total_km'] == 0


def test_send_chat_reports_twitch_drop(tmp_path):
    import httpx
    from test_twitch_auth_rewards import gateway
    gw = gateway(tmp_path)
    gw.configured = lambda: True
    gw.bot_user_id = "bot"
    gw._api_request = AsyncMock(return_value=httpx.Response(200, json={"data":[{"is_sent":False,"drop_reason":{"code":"automod_held","message":"Held"}}]}))
    assert asyncio.run(gw.send_chat("hello")) is False
    assert "automod_held" in gw.last_error


def test_all_monster_assets_are_included():
    from pathlib import Path
    from backend.monsters import MONSTERS
    folder = Path(__file__).resolve().parents[1]/"web"/"static"/"monsters"
    assert len(MONSTERS) == 20
    for monster in MONSTERS:
        image = folder/(monster["id"]+".png")
        assert image.is_file(), monster["id"]
        assert image.stat().st_size > 10000
        with image.open("rb") as fh:
            assert fh.read(8) == b"\x89PNG\r\n\x1a\n"
