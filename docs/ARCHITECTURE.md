# BicycleStreamUI architecture

The backend process is the single source of truth. `bridge.py` keeps the original `gc_live.json` contract and additionally emits `session_id`, allowing the challenge layer to distinguish a reconnect/new session from normal increasing distance.

```text
bridge.py / ANT+ telemetry ----> gc_live.json ----> StreamRuntime
Twitch EventSub ---------------------------------> StreamRuntime
Admin/Test Lab ----------------------------------> StreamRuntime
                                                     |
                          +--------------------------+-----------------------+
                          |                          |                       |
                  ChallengeService             BossEngine       PhysicalChallengeManager
                  JSON state                   SQLite stats      TrainerControlService
                          |                          |                       |
                          +--------------- EventManager --------------------+
                                             |
                                      WebSocket / REST
                         +-------------------+------------------+
                         |                   |                  |
                challenge-overlay      event-overlay      dashboard/admin
```

## Idempotency

Distance triggers are persisted in `data/challenge_state.json`. A 10/100 km milestone, goal, and boss distance mark therefore cannot fire twice merely because the app restarts. Twitch EventSub messages are deduplicated in-memory by `metadata.message_id`; long-term boss effects are additionally protected by SQLite uniqueness constraints (`fight_id,user_id` and reward keys).

## Simulation isolation

Simulation uses separate in-memory boss and physical challenge instances and never writes simulated hits, medipaks, fights, or rewards to SQLite. Simulated challenge percentages are view overrides. Real bike telemetry can continue to update the real challenge independently; simulated values themselves never touch production state.

## Event scheduling

`EventManager` keeps two concepts: a complete transient event stream (needed for every emote projectile) and a priority queue for central fullscreen callouts. High-volume `BOSS_HIT` events have zero callout duration and are rendered directly as projectiles. Major events can pre-empt substantially lower-priority callouts.

## Extension hooks

`backend/future_hooks.py` contains disabled `BettingModule` and `MilestoneDedicationModule` interfaces. They intentionally contain no visible/active feature logic.
