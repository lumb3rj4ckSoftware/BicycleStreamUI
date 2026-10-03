# BicycleStreamUI – 1000 km Oktober

Lokales Stream-Event-System für die **1000-km-Oktober-Challenge**. Das Projekt erweitert den bisherigen `bridge.py`/`gc_live.json`-Datenfluss um einen Python-Backend-Prozess, vier getrennte Browser-Oberflächen für OBS, persistente Challenge-/Bossdaten, Twitch-Interaktion, ein nicht-destruktives Testlabor und eine fail-safe gekapselte Trainersteuerung.

## Was ist enthalten?

- **Challenge Overlay** – horizontale 1000-km-Leiste, Tageswert, Planstatus, Rest, benötigter Schnitt, 100-km-Marker, Physical-Challenge-Bar, Heat 0–3 und Canvas-Partikel.
- **Event Overlay** – transparente 1920×1080 Fullscreen-Source für 10/100/1000-km-Events, Back-on-Track, Gifts, Raids, Bossfights, Emote-Projektile, Medipaks und Rider Boost.
- **Dashboard** – modernisierte, weiterhin unabhängige Anzeige für Speed, Power, Distanz, HR, Cadence, Durchschnittswerte und Zonen.
- **Admin / Testlabor** – Feature Flags, Korrekturen, Config, Overlay-Previews, Simulation aller wichtigen Zustände, Damage-Stats, Trainer-Diagnose und Not-Aus.
- **Persistenz** – atomarer Challenge-State als JSON; Boss-/Damage-/Teilnehmer-/Reward-Daten in SQLite.
- **Twitch** – EventSub WebSocket für Chat, Subscription Gifts, Raids und Custom Reward Redemptions; Commands `!km`, `!heute`, `!plan`, `!next`, `!topdamage`, `!damage`, optional `!boss`.
- **Boss-System** – standardmäßig klein alle 20 km, groß an jeder 100-km-Marke; Distanzintervalle und 150/270-s-Dauern sind konfigurierbar, dazu Chatter-basierte HP, 1×/2× Damage, Lifetime Ranking und Reward-Eligibility bei Sieg.
- **KICKR CORE 2** – Trainer-Control standardmäßig AUS; Capability-Test, 0/1/2 %, Restore und Not-Aus. Details unter [docs/TRAINER_FEC.md](docs/TRAINER_FEC.md).

## Schnellstart unter Windows 11

Voraussetzung: Python 3.10+ und – für ANT+ – ein funktionsfähiger ANT+-USB-Dongle.

### 1. Einmalig einrichten

```bat
setup_windows.bat
```

Das Script erstellt `.venv` und installiert exakt die Abhängigkeiten aus `requirements.txt`.

### 2. Twitch Login

Keine Tokens mehr manuell in `.env` eintragen. Nach dem Start im Adminpanel auf **„Mit Twitch anmelden“** klicken. `.env` bleibt nur für optionale Overrides/Legacy-Setups vorhanden.

### 3. Echtbetrieb starten

```bat
BicycleStreamUI.bat
```

Dadurch werden der ANT+-Bridge-Prozess, das Backend auf `127.0.0.1:5050` und das Adminpanel gestartet. `Ctrl+C` beendet die verwalteten Prozesse sauber.

### 4. Ohne ANT+-Hardware testen

```bat
BicycleStreamUI_TEST.bat
```

Der Bridge-Prozess erzeugt plausible Test-Telemetrie. **Im Test-Start ist die Kilometer-Persistenz gesperrt**, damit Fake-Daten die echte 1000-km-Challenge nicht verändern. Danach im Browser:

- Admin: `http://127.0.0.1:5050/admin`
- Challenge: `http://127.0.0.1:5050/challenge-overlay`
- Event: `http://127.0.0.1:5050/event-overlay`
- Dashboard: `http://127.0.0.1:5050/dashboard`

## OBS Browser Sources

| Source | URL | Empfehlung |
| --- | --- | --- |
| Challenge | `http://127.0.0.1:5050/challenge-overlay` | 1400×230, oben mittig; Breite 1200–1600 sinnvoll |
| Event/Boss | `http://127.0.0.1:5050/event-overlay` | **1920×1080**, volle Szene, transparenter Hintergrund |
| Sub-Info | `http://127.0.0.1:5050/sub-info-overlay` | **460×340**, transparente Browserquelle |
| Dashboard | `http://127.0.0.1:5050/dashboard` | z. B. 620×740, frei platzierbar |
| Admin | `http://127.0.0.1:5050/admin` | Nicht als Stream-Source; nur lokale Steuerung |

Die vier Seiten sind voneinander unabhängig. `overlay_stein_cycling.html` bleibt als Kompatibilitäts-Shim erhalten und leitet auf das neue Dashboard um.

## Challenge-Logik

Standard: **01.10.2026–31.10.2026, 1000 km**. Ziel, Zeitraum, Intervalle, Heat-Schwellen und weitere Werte stehen in `config/challenge_config.json` und sind zusätzlich im Adminpanel änderbar.

Der Planstatus bewertet am laufenden Tag primär die **vollständig vergangenen Tage**. Am 1. Oktober um 08:00 sind 0 km deshalb nicht automatisch „hinter Plan“. Zusätzlich werden Tagesziel, Restkilometer, verbleibende Tage und der nötige Rest-Tagesdurchschnitt angezeigt.

Live-Distanz wird als Session-Messwert behandelt. Das Backend persistiert nur positive, plausible Deltas. Bei neuer Session, Counter-Reset oder Reconnect wird eine Baseline gesetzt statt Distanz doppelt zu verbuchen. Getriggerte 10-/100-km-Events, Bossmarken und das Ziel werden idempotent gespeichert.

## Gifts / Raid / Physical Challenges

Die Gift-Logik bezieht sich **immer auf ein einzelnes Gift-Event**:

- genau 5 Subs → `SPRINT +30s`; ein weiterer separater 5er-Gift verlängert einen laufenden normalen Sprint um weitere 30 s.
- genau 10 Subs → 1 % Grade für 90 s; kein automatisches 5er-Cascade.
- genau 15 Subs → 2 % Grade + Standing Sprint für 90 s; keine niedrigeren Pakete zusätzlich.
- Vielfache >15 → Default `15 einmal + Rest als 5er`, also 20 = 15 + 5. Die Zerlegung ist über `physical_challenges.higher_multiple_strategy` konfigurierbar (`highest_once_then_fives`, `repeat_highest_then_fives`, `fives_only`, `exact_only`).
- Raid → Viewerzahl = Standing-Sekunden; optionaler Cap ist konfigurierbar.

Widersprüchliche Aufgaben werden vom `PhysicalChallengeManager` serialisiert.

## Bossfights

- Small Boss: Default 20, 40, 60, 80, 120 … km, Standard 150 s.
- Major Boss: Default 100, 200, 300 … km, Standard 270 s und ersetzt dort den Small Boss.
- Die Distanzmarken stehen als `boss.interval_km` (Default 20) und `boss.major_interval_km` (Default 100) in der Konfiguration; das Major-Intervall muss ein Vielfaches des kleinen Intervalls sein.
- HP: Baseline + aktiver Chatter-Faktor (5-Minuten-Fenster), mit Min/Max.
- Alle erkannten Emote-Vorkommen einer Chatnachricht werden in ihrer Reihenfolge als Salve auf derselben Flugbahn angezeigt, auch Wiederholungen. Eine Nachricht = ein Treffer; Nicht-Sub 1 Damage, Sub 2 Damage.
- Twitch-native Emotes werden aus strukturierten Chat-Fragments gelesen; 7TV/BTTV/FFZ laufen über einen fehlertoleranten Provider-Resolver.
- Non-Sub: 1 Damage; Sub: 2 Damage und 2× Reward-Multiplier.
- Alle gültigen Hits werden serverseitig gezählt; der Browser zeigt bis zu 200 Projektile gleichzeitig; weitere werden zeitversetzt gestartet.
- Medipak: max. 1 pro `user_id` und Fight; Default +10 s.
- Rider Assist: ab 30 km/h Charge; höhere Rate bei 35 und 40+; Default-Cap +60 s Small / +120 s Big.
- Sieg erzeugt pro Teilnehmer genau einen `reward_eligibility`-Datensatz; Niederlage erzeugt keinen Win-Reward.

## Twitch Setup

Die Twitch-Konfiguration läuft jetzt **ohne manuelles Kopieren von Access Tokens oder User-IDs**. Im Adminpanel gibt es den Bereich **„Twitch Login & Medipak-Kanalbelohnung“**:

1. `BicycleStreamUI.bat` oder `BicycleStreamUI_TEST.bat` starten.
2. `http://127.0.0.1:5050/admin` öffnen.
3. **„Mit Twitch anmelden“** drücken.
4. Twitch öffnet die Device-Aktivierung. Einmal anmelden und die angezeigten Berechtigungen freigeben.
5. Das Backend holt Access Token, Refresh Token, Broadcaster-ID, Bot-ID und EventSub-ID automatisch und speichert sie lokal in `data/twitch_auth.json`. Tokens werden **nie** im Browser-State ausgegeben.
6. Die Twitch-Integration wird nach erfolgreicher Anmeldung automatisch aktiviert.

Verwendete Scopes:

- `user:read:chat` – Chatnachrichten über EventSub lesen.
- `user:write:chat` – Antworten für `!km`, `!damage` usw. senden.
- `channel:read:subscriptions` – einzelne Gift-Sub-Events empfangen.
- `channel:manage:redemptions` – Medipak-Kanalbelohnung erstellen/verwalten und Einlösungen zurückerstatten.

Der Login nutzt den **Twitch Device Code Flow für Public Clients**. Dadurch ist kein Client Secret nötig. Die Client-ID ist in `config/challenge_config.json -> twitch.client_id` konfigurierbar und kann weiterhin über `TWITCH_CLIENT_ID` überschrieben werden. Die alten `.env`-Felder für Token/User-IDs werden aus Kompatibilitätsgründen noch gelesen, sind für den normalen Betrieb aber nicht mehr erforderlich.

### Automatische Medipak-Kanalbelohnung

Nach dem ersten erfolgreichen Twitch-Login legt das System automatisch die Kanalbelohnung an:

- Titel: `Medipak`
- Kosten: `500` Kanalpunkte
- Prompt: in `config/challenge_config.json` konfigurierbar
- `should_redemptions_skip_request_queue = false`, damit offene Einlösungen zurückerstattet werden können

Titel, Kosten und Prompt sind direkt im Adminpanel änderbar. Die Belohnung wird anhand ihrer Twitch-Reward-ID lokal gespeichert. Existiert bereits eine gleichnamige Belohnung, die von einer anderen Twitch-App/manuell angelegt wurde, wird **nicht** so getan, als könne BicycleStreamUI diese verwalten: Das Adminpanel zeigt einen klaren Fehler und verlangt Umbenennen/Löschen oder einen anderen Titel.

Die Twitch-API erlaubt Erstellen/Verwalten eigener Channel-Point-Rewards nur auf dafür berechtigten Kanälen. Gibt Twitch 403 zurück (z. B. Kanal nicht Affiliate/Partner oder Reward von einer anderen App erstellt), wird der Fehler im Adminbereich angezeigt; Chat/Gifts/Raids können trotzdem weiter funktionieren.

### Medipaks zurückgeben / löschen

Unter **„Offene Medipak-Einlösungen“** werden `UNFULFILLED`-Einlösungen angezeigt:

- **Zurückgeben** → setzt die Redemption auf `CANCELED`; Twitch erstattet dem Zuschauer die Kanalpunkte.
- **Erledigt** → setzt sie auf `FULFILLED`; danach kann sie über die Twitch-API nicht mehr storniert werden.
- Ungültige Einlösungen (kein Boss aktiv oder zweites Medipak desselben Nutzers im selben Bossfight) werden automatisch auf `CANCELED` gesetzt und damit zurückerstattet.
- **Belohnung löschen** → erstattet zuerst alle noch offenen Einlösungen und löscht anschließend die Reward. Die automatische Neuerstellung wird dabei deaktiviert, damit die Reward nach einem Neustart nicht ungefragt wieder erscheint. Ein Klick auf **„Erstellen / Speichern“** aktiviert die automatische Verwaltung wieder.

Access/Refresh Tokens werden lokal in `data/twitch_auth.json` gespeichert; die Datei ist in `.gitignore` ausgeschlossen. Public-Client-Refresh-Tokens werden bei jedem Refresh durch den neu gelieferten Refresh-Token ersetzt. Das Backend validiert die Session regelmäßig und versucht bei abgelaufenem Access Token automatisch zu refreshen.

## Nicht-destruktives OBS-Testlabor

`Admin → Testlabor` kann simulieren:

- 0/10/25/50/75/99/100 % Fortschritt
- ahead / on_track / behind / back-on-track
- Heat 0 / 30 / 35 / 42 km/h
- 10 km / 100 km / 1000 km
- 5 / 10 / 15 / 20 Gift inklusive konfigurierbarer >15-Zerlegung
- Raid mit freier Viewerzahl
- Small/Big Boss mit frei wählbarer Chatterzahl
- Emote-Hit mit Sub-Flag
- Medipak, Rider Boost, Win/Loss

Simulierte Eingaben nutzen **separate In-Memory Physical-/Boss-Instanzen** und verändern keine produktiven Challenge-/Damage-/Reward-Daten. Reale Bike-Telemetrie kann unabhängig weiter in die echte Challenge einfließen; reale Twitch-Events werden während aktiver Simulation ignoriert, damit sie nicht mit simulierten Boss-/Physical-Events kollidieren. Der Modus lässt sich nicht starten, während ein echter Boss oder eine echte Physical Challenge aktiv ist.

## Daten & Backup

- `data/challenge_state.json` – atomar geschriebener Challenge-State.
- `data/stream_state.sqlite` – wird beim Start automatisch angelegt/migriert.
- `data/bicyclestreamui.log` – rotierendes Log.
- Admin `Backup` erstellt Zeitstempel-Kopien von JSON und SQLite.
- Vor einem vollständigen Challenge-Reset wird automatisch ein Backup erstellt.

Empfehlung: Vor größeren Änderungen den gesamten `data/`-Ordner zusätzlich kopieren.

## Trainer / ANT+ FE-C

Der KICKR CORE 2 wird capability-basiert behandelt. Trainer Control ist standardmäßig deaktiviert. Beim Einschalten wird zuerst geprüft, ob der gewählte Adapter eine kontrollierbare Track-Resistance/Grade-Fähigkeit bereitstellt. Schlägt das fehl, laufen Overlay und Physical Challenge weiter, aber es wird **kein erfolgreicher Trainerbefehl vorgetäuscht**.

Der im Bestandsprojekt verwendete OpenANT-Weg bleibt für das **Empfangen/Scannen** der Bike-Daten erhalten. Für Grade-Control siehe die technische Begründung und den externen FE-C-Helper-Adapter in [docs/TRAINER_FEC.md](docs/TRAINER_FEC.md).

## Architektur

Kurzform:

```text
ANT+/bridge.py ──> gc_live.json ──┐
                                  │
Twitch EventSub ──────────────────┼─> StreamRuntime / Services
                                  │       ├─ Challenge JSON
Admin / Testlabor ────────────────┘       ├─ SQLite Stats
                                          ├─ EventBus
                                          ├─ BossEngine
                                          ├─ PhysicalChallengeManager
                                          └─ TrainerControlService
                                                  │
                          WebSocket state/events ──┼─ challenge-overlay
                                                  ├─ event-overlay
                                                  ├─ dashboard
                                                  └─ admin
```

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Tests

```bat
.venv\Scripts\python -m pytest -q
```

Der Implementierungsstand enthält Tests für Delta-/Reconnect-Logik, Planlogik, konfigurierbares Gift-Mapping, Raids, konfigurierbare Boss-Spawns/HP, 2× Sub-Damage, Medipaks, Lifetime-Ranking, Reward-Idempotenz, Fake Twitch + Fake Trainer, Simulationsisolation, HTTP/HTML-Overlay- und API-Smoke-Tests sowie einen 5000-Hit-Stresstest.

Zusätzlicher lokaler Smoke-Test:

```bat
BicycleStreamUI_TEST.bat
```

Dann im Adminpanel die drei Overlay-Previews öffnen.

## Troubleshooting

**`gc_live.json` fehlt / Dashboard bleibt bei 0:** Bridge-Fenster prüfen. Testweise `BicycleStreamUI_TEST.bat` starten. ANT-Modus nutzt weiterhin OpenANT-Scan und die konfigurierten Geräte-IDs in `bridge.py`.

**Port 5050 belegt:** `set BICYCLE_STREAM_PORT=5051` vor dem Start oder `launcher.py --port 5051`. OBS-URLs entsprechend anpassen.

**Twitch bleibt offline:** Im Adminbereich `Twitch Login & Medipak-Kanalbelohnung` prüfen. Fehlende Scopes, OAuth-/EventSub-Fehler und Reward-API-Fehler werden dort angezeigt. Bei Bedarf `Mit Twitch anmelden` erneut ausführen. Tokens werden nie im Browser-State ausgegeben.

**Trainer gefunden, Grade aber nicht steuerbar:** Das ist ein absichtlicher Safe-State. `Admin → Trainer` zeigt Adapter/Capability/Fehler. Siehe `docs/TRAINER_FEC.md`.

**Zwift/Wahoo kontrolliert den Trainer:** Nicht aggressiv übernehmen. Andere Controller schließen bzw. deren Control-Verbindung beenden, danach Capability-Test erneut ausführen.

## Verzeichnisstruktur

```text
backend/                  Services, Runtime, EventBus, Twitch, Boss, Trainer, Persistenz
web/                      Challenge/Event/Dashboard/Admin + Assets
config/challenge_config.json
data/challenge_state.json
docs/                     Architektur + FE-C Hinweise
tests/                    Unit-, Integrations-, Smoke- und Stresstests
bridge.py                 Legacy-kompatibler Bike-Daten-Bridge
launcher.py               Prozessmanager für Bridge + Backend
BicycleStreamUI.bat       Windows-Echtstart
BicycleStreamUI_TEST.bat  Windows-Teststart
```

## Future Hooks

`BettingModule` und `MilestoneDedicationModule` existieren nur als Architektur-Hooks. Die Flags sind bewusst nicht aktivierbar; es wurde **keine** Punkte-/Wettökonomie erfunden.


## Update: 20 Monster und Chat im SIM-Modus

Lies `UPDATE_MONSTER.md` für Installation, HP-Beispiele und den Testablauf.


## Salven-, Bosszeiten- und Sub-Overlay-Update

Aktuelle Anleitung und Prüfergebnisse: **UPDATE_SALVEN.md**.


## Kompaktes Sub-Overlay und Finalboss-Abschluss

Aktuelle Anleitung: **UPDATE_FINALE_KOMPAKT.md**. Zweites Sub-Overlay: `/sub-info-compact-overlay` (360 × 150). Abschlussfeuerwerk nach Sieg über den Ziel-Boss; Timer und Siegmeldung im Event-Overlay deutlich größer.


Twitch-Anmeldung: Das Update V4 korrigiert die Behandlung ungültiger Tokens und Wiederholungen nach Netzwerkfehlern. Installation und Prüfergebnisse stehen in `UPDATE_TWITCH_AUTH_V4.md`.


Update V5: Unabhängige Prozessüberwachung und Twitch-Anmeldung im Hintergrund; Installation und Diagnose in `UPDATE_STARTSTABILITAET_V5.md`. Die kompakte Sub-Übersicht verwendet die Zeilen der großen Übersicht mit Zeit rechts und Erklärung unter dem Namen. Empfohlene OBS-Größe: 460 × 170 Pixel.
