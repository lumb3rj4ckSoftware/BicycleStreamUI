# KICKR CORE 2 / ANT+ FE-C control

Wahoo documents the KICKR CORE 2 with ANT+, ANT+ FE-C, electromagnetic controlled resistance and up to 16% simulated grade. The app therefore exposes 0%, 1%, 2% and restore controls, but only after a capability check.

## Why the control path is isolated

The existing project uses `python -m openant scan` as a robust receiver path for speed/power/HR/cadence. Receiving ANT+ Fitness Equipment data does **not** by itself prove that the current Python/OpenANT setup is acting as a tested FE-C master controller. To avoid sending guessed protocol frames to a trainer, real grade commands are behind `TrainerControlService` and an external helper contract.

The helper configured via `BICYCLE_FEC_HELPER` must support:

```text
<helper> status
<helper> grade 0
<helper> grade 1
<helper> grade 2
<helper> restore
```

Each command prints one JSON object. `status` must report `found`, `connected`, `controllable` and `grade` (or `track_resistance`). Only if all required capabilities are true does the application mark control active. Failure disables control and leaves the visual challenge running.

The included `tools/fec_helper.py` is intentionally a **safe stub** and reports unsupported instead of pretending to control hardware. Replace it with a validated FE-C master implementation or vendor-specific bridge, then set for example:

```env
BICYCLE_FEC_HELPER=C:\Tools\kickr-fec-helper.exe
```

## Manual acceptance sequence

1. Close Zwift, Wahoo and other applications that may own trainer control.
2. Open Admin → Trainer.
3. Enable control and verify the exact device/capabilities.
4. While off the bike or at safe low power, test 0%, 1%, 2%, then Restore.
5. If any command fails, leave control disabled. The stream UI continues without resistance changes.
6. The NOT-AUS button clears physical challenge queues and calls Restore.

The application never aggressively steals control from another controller.

References checked for this implementation:
- Wahoo KICKR CORE 2 Smart Trainer Information & FAQ: https://support.wahoofitness.com/hc/en-us/articles/28096790110354-KICKR-CORE-2-Smart-Trainer-Information-FAQ
- Wahoo trainer control modes: https://support.wahoofitness.com/hc/en-us/articles/28408412793490-Trainer-control-modes-for-KICKR-CORE-SNAP-or-BIKE-in-the-Wahoo-app
