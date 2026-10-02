from backend.boss import BossEngine


def user(uid="u1", name="User"):
    return {"user_id":uid,"login":name.lower(),"display_name":name}


def test_hp_scaling_monotonic(config, services):
    _, db = services
    engine = BossEngine(config, db)
    small = [engine.hp_for("small", n) for n in [0,1,5,20,100]]
    major = [engine.hp_for("major", n) for n in [0,1,5,20,100]]
    assert small == sorted(small)
    assert major == sorted(major)
    assert major[0] > small[0]


def test_subscriber_double_damage_and_lifetime(config, services):
    _, db = services
    e = BossEngine(config, db)
    e.start("small",20,0,now=100)
    emote={"id":"25","code":"Kappa","url":"x"}
    h1=e.hit(user(),subscriber=False,emote=emote,now=101)
    h2=e.hit(user(),subscriber=True,emote=emote,now=102)
    assert h1["damage"] == 1 and h2["damage"] == 2
    row=db.user_damage("u1")
    assert row["damage"] == 3 and row["hits"] == 2 and row["fights"] == 1


def test_medipack_once_per_user_per_fight(config, services):
    _, db = services
    e=BossEngine(config,db);e.start("small",20,0,now=100)
    a=e.medipack(user(),now=101);b=e.medipack(user(),now=102)
    assert a["applied"] is True
    assert b["applied"] is False
    assert e.active.medipacks == 1


def test_rewards_only_on_win_and_idempotent(config, services):
    _, db = services
    emote={"id":"25","code":"Kappa","url":"x"}
    e=BossEngine(config,db);e.start("small",20,0,now=100);e.hit(user(),subscriber=True,emote=emote,now=101)
    fight_id=e.active.fight_id
    summary=e.finish("won",now=110)
    assert len(summary["reward_eligibility"]) == 1
    # DB uniqueness means another finish write cannot duplicate reward.
    again=db.finish_fight(fight_id,"won",34,0,0)
    assert again == []
    assert db.count("reward_eligibility") == 1
    assert db.user_damage("u1")["wins"] == 1

    e2=BossEngine(config,db);e2.start("small",40,0,now=200);e2.hit(user("u2","Other"),subscriber=False,emote=emote,now=201);e2.finish("lost",now=210)
    assert db.count("reward_eligibility") == 1


def test_rider_assist_caps(config, services):
    _, db=services
    e=BossEngine(config,db);e.start("small",20,0,now=100)
    for _ in range(1000):
        e.rider_charge(45,1)
    assert e.active.rider_bonus_s <= config["boss"]["rider_small_cap_seconds"]
