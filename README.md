## Kurz, was du noch tun musst

[ANT] [11:36:55] Device fitness_equipment_34628 broadcast standard_power data: PowerData(instantaneous_power=140, average_power=137, left_power=-1, right_power=-1, torque=0.03, angular_velocity=2.28, cadence=77)
Traceback (most recent call last):
  File "E:\Arbeit\Twitch-Streaming\BicycleStreamUI\bridge.py", line 378, in <module>
    main()
  File "E:\Arbeit\Twitch-Streaming\BicycleStreamUI\bridge.py", line 371, in main
    run_ant_mode(args)
  File "E:\Arbeit\Twitch-Streaming\BicycleStreamUI\bridge.py", line 313, in run_ant_mode
    atomic_write_json(json_path, dataclasses.asdict(metrics))
  File "E:\Arbeit\Twitch-Streaming\BicycleStreamUI\bridge.py", line 52, in atomic_write_json
    os.replace(tmp_path, path)
PermissionError: [WinError 5] Zugriff verweigert: 'gc_live.json.tmp' -> 'gc_live.json'

============================================================
[ENDE] BicycleStreamUI wurde beendet.
Dr├╝cke eine beliebige Taste zum Schlie├ƒen ...

# Vorbereiten
```
python -m venv .venv
```

# Windows:

```
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\activate
pip install openant
```

## Testen
```
python bridge.py --mode test --output gc_live.json --interval 0.5
```

## Normal laufen lassen
```
python bridge.py --mode ant --output gc_live.json --interval 0.5
```

### In dem HTML anpassen (optional)

- MAX_HR auf deine maximale HF setzen
- FTP auf deine FTP in Watt setzen

### OBS

- Browserquelle → Häkchen „Lokale Datei“ → overlay_stein_cycling.html
- Größe z. B. 360×500, dann im Layout hinsetzen wo du willst.

---

## Ideen für den Stream

### 1. Live-Overlays & Effekte (richtiges Stream-Feeling) 

Power-basierte Effekte: 
- Bildschirm wackelt, wenn du über 800 Watt sprintest
- Neon-Glow der Cam verstärkt sich je nach Power
- Flammen um dich, wenn du >1000 W trittst
- Speed Lines ab 40 km/h
- Blitz-Effekt, wenn du die höchste HR-Zone erreichst

Fortschrittsbalken / Challenges:
- „Kalorien-Goal“ – Balken füllt sich
- „KM Ziel des Tages“ – 20 km, 50 km etc.
- „Power-Zonen-Meter“ – zeigt, wie lange du in Zx bist
- „Watt-Peak“ – Anzeige der heutigen maximalen Leistung
- „Sprint Counter“ – wie oft du >800W warst

Mini-Map/Heatmap:
- Zeige eine Heatmap, wie viele Sekunden du in welcher HR-Zone warst
- Zeige deine „Rundenzeiten“ → jede 1 km wird als eigener Split angezeigt

### 2. Chat-Interaktion

Chat bestimmt dein Training:
- „Chat Challenge: Für jeden ‚PUSH‘ im Chat → +5 Watt für 10 Sekunden“
- „Chat tippt: HF < 140 = gemütlich, HF 140–160 = normal, >160 = Sprint!“
- „Lieblings-Challenge: Chat schreibt ‘SPRINT’ → du musst 5 Sekunden all-out gehen“

Live-Polls:
- Sprint jetzt?
- Gang schwerer?
- Herzfrequenz halten?
- 1 Minute Wiegetritt vs 1 Minute Sitzen?

#### Sounds und Trigger

- Sounds auslösen: „Push It“, Jingles, Alarm bei HF > 180
- Spezial-Sounds bei hohen Watt-Zahlen (z. B. > 900 W)

### 3) Gamification — mach ein Spiel draus

#### a) XP-System

- 10 kcal → XP
- Bonus für Watt-PRs
- Level-Anzeige im Overlay

#### b) Boss Fights

- Boss-HP z. B. 3000
- Schaden = Watt (1 W = 1 DMG)
- Chat spendiert Power-Ups
- Beim Sieg: Animation + Lootbox

#### c) Sprint Rooms

- Periodische „Speed-Rooms“ mit Countdown
- Nach dem Sprint: Peak Power, Max Speed, Dauer, Vergleich zur letzten Runde

### 4) Kamera-Szenen & Automatisierung

#### Cam-Setups

- Face-Cam, Bike-Side-Cam, Pedal/Chainring-Cam, HR-Belt-Cam
- Automatisches Cam-Switching: z. B. >350 W → Sprint-Cam, <200 W → normale Cam

#### LED-Strip Reaktionen (WLED + OBS Websocket)

- LED-Farbe nach HF: Rot = hoch, Blau = locker, Orange = Sprint, Violett = Peak

### 5) Echte Belohnungen / Interaktionen

#### Hydration Reminder

- Chat-Befehl `HYDRATE` → Sound + Wasser-Overlay

#### Kalorien-Challenges

- 100 kcal → 10 Sit-Ups
- 200 kcal → 15 Liegestütze
- 300 kcal → 1 min Plank

#### Pedal Trivia

- Alle 5 km eine Quizfrage — nur antworten, wenn Watt > 200

### 6) Social Media: Clips & Zusammenfassungen

- Sprint-Highlights (Peak Power)
- Heatmap der HR-Zonen
- Best-of Chat Moments
- Tages-/Session-Zusammenfassungen

### 7) Technik-Specials

#### KI-generierte Coach-Stimme (TTS)

- Automatische Ansagen, z. B. „Du bist in Z3 — +10 W“ oder „Noch 50 m!“
- Steuerbar über Overlay-JSON

#### KI-gestützter Virtual Partner

- Live-Vergleich: „Ich fahre X — du bist Y behind/ahead“
- Power- und Distanz-Gap wie in Zwift

---

Wenn du willst, übernehme ich die Anpassung der Variablen direkt in `overlay_stein_cycling.html` oder ergänze eine minimale Quickstart-Anleitung für GoldenCheetah → OBS → Overlay.

