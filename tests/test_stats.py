from backend.boss import BossEngine


def test_topdamage_and_user_rank(config, services):
    _,db=services
    e=BossEngine(config,db);e.start('small',20,0,now=100)
    em={'id':'25','url':'x'}
    for _ in range(3): e.hit({'user_id':'a','login':'a','display_name':'Alice'},subscriber=True,emote=em)
    for _ in range(4): e.hit({'user_id':'b','login':'b','display_name':'Bob'},subscriber=False,emote=em)
    top=db.top_damage(5)
    assert top[0]['user_id']=='a' and top[0]['damage']==6
    assert db.user_damage('b')['rank']==2


def test_rank_is_deterministic_for_complete_ties(config, services):
    _, db = services
    em = {"id": "25", "url": "x"}
    e = BossEngine(config, db)
    e.start("small", 20, 0, now=100)
    # Same damage/hits/fights and the same timestamp: stable user_id is the final tie-breaker.
    e.hit({"user_id":"a","login":"a","display_name":"A"}, subscriber=False, emote=em, now=101)
    e.hit({"user_id":"b","login":"b","display_name":"B"}, subscriber=False, emote=em, now=101)
    assert [row["user_id"] for row in db.top_damage(2)] == ["a", "b"]
    assert db.user_damage("a")["rank"] == 1
    assert db.user_damage("b")["rank"] == 2
