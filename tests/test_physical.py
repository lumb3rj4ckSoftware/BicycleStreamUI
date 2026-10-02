from backend.physical import PhysicalChallengeManager, gift_packages
from backend.trainer import FakeTrainerAdapter, TrainerControlService


def manager(config):
    trainer = TrainerControlService(config, FakeTrainerAdapter())
    trainer.enable()
    return PhysicalChallengeManager(config, trainer), trainer


def test_gift_mapping_exact_and_default():
    assert gift_packages(5) == [5]
    assert gift_packages(10) == [10]
    assert gift_packages(15) == [15]
    assert gift_packages(20) == [15, 5]
    assert gift_packages(7) == []


def test_two_separate_fives_extend_sprint(config):
    m, _ = manager(config)
    out1 = m.enqueue_gift(5, now=100)
    assert out1 == [(5, "started")]
    before = m.active.end_at
    out2 = m.enqueue_gift(5, now=110)
    assert out2 == [(5, "extended")]
    assert m.active.end_at == before + 30


def test_direct_10_and_15_do_not_cascade(config):
    m, trainer = manager(config)
    assert [p for p,_ in m.enqueue_gift(10, now=100)] == [10]
    assert m.active.kind == "climb" and m.active.grade_percent == 1
    m.tick(now=191)
    assert trainer.adapter.commands[-1][0] in {"restore", "grade"}
    m2, _ = manager(config)
    assert [p for p,_ in m2.enqueue_gift(15, now=100)] == [15]
    assert m2.active.kind == "standing_climb" and m2.active.standing


def test_raid_time_and_cap(config):
    m, _ = manager(config)
    task, _ = m.enqueue_raid(73, now=100)
    assert task.duration_s == 73
    config["physical_challenges"]["raid_cap_enabled"] = True
    config["physical_challenges"]["raid_cap_seconds"] = 60
    m2, _ = manager(config)
    task2, _ = m2.enqueue_raid(73, now=100)
    assert task2.duration_s == 60
