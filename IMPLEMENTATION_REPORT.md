# Implementierungs- und Prüfbericht

Stand: 2026-10-01

## Umgesetzt

Die Umsetzung folgt dem finalen Implementierungsauftrag für die 1000-km-Oktober-Challenge. Enthalten sind ein lokales FastAPI-Backend, persistenter Challenge-State, SQLite-Statistiken, getrennte OBS-Browser-Sources, zentrales Event-System, Physical-Challenge-Queue, Twitch-EventSub-Adapter, Bossfights, Damage-Ranking, Reward-Eligibility, nicht-destruktives Admin-Testlabor und eine fail-safe gekapselte Trainer-Control-Schnittstelle.

Wichtige URLs nach dem Start:

- Admin: http://127.0.0.1:5050/admin
- Challenge Overlay: http://127.0.0.1:5050/challenge-overlay
- Fullscreen Event/Boss Overlay: http://127.0.0.1:5050/event-overlay
- Classic Dashboard: http://127.0.0.1:5050/dashboard

## Ergänzung: automatischer Twitch-Login und Medipak-Verwaltung

Die frühere manuelle `.env`-Pflege von Access Token und Twitch-User-IDs ist für den normalen Betrieb nicht mehr erforderlich.

Umgesetzt wurden:

- Twitch Device Code Login direkt aus dem Adminpanel.
- Automatische Übernahme und lokale Speicherung von Access Token und Refresh Token.
- Automatische Ermittlung von Broadcaster-ID, Bot-ID und EventSub-ID aus dem validierten User-Token.
- Regelmäßige Token-Validierung und automatischer Refresh; neu ausgegebene Refresh Tokens ersetzen den vorherigen Token atomar.
- Token-Datei `data/twitch_auth.json` ist lokal, wird nicht an die Browser-Oberfläche ausgegeben und ist in `.gitignore` ausgeschlossen.
- Nach erfolgreichem Login wird die verwaltete Twitch-Kanalbelohnung `Medipak` automatisch erstellt, sofern `medipack_auto_create` aktiv ist.
- Titel, Kosten und Prompt der Belohnung sind im Adminpanel änderbar.
- Die Reward-ID wird persistent gespeichert und für EventSub verwendet.
- Fremde/manuell angelegte Rewards mit identischem Titel werden erkannt; das System behauptet in diesem Fall nicht, sie verwalten zu können.
- Offene Medipak-Einlösungen werden im Adminpanel angezeigt.
- `Zurückgeben` setzt eine offene Einlösung auf `CANCELED`, sodass Twitch die Kanalpunkte zurückerstattet.
- `Erledigt` setzt eine offene Einlösung auf `FULFILLED`.
- Ungültige Medipaks (kein Boss aktiv oder zweites Medipak desselben Users im selben Kampf) werden bei einer app-verwalteten Reward automatisch zurückerstattet.
- Beim Löschen der Medipak-Belohnung werden offene Einlösungen zuerst zurückerstattet und erst danach wird der Reward gelöscht.
- Nach manuellem Löschen wird `medipack_auto_create` deaktiviert, damit die Reward nach einem Neustart nicht ungefragt neu entsteht. `Erstellen / Speichern` aktiviert die Verwaltung wieder.
- Twitch-Abmeldung widerruft nach Möglichkeit den Access Token und entfernt die lokal gespeicherte OAuth-Datei.

## Automatisierte Prüfung

Finaler Lauf im Build-Container:

```text
python -m pytest -q
.........................                                                [100%]
25 passed in 5.39s
```

Die Test-Suite deckt zusätzlich zur bisherigen Funktionalität nun explizit ab:

- Device-Code-Login und persistierte Token-/User-ID-Übernahme ohne Token-Leak in den Overlay-State.
- automatische Medipak-Erstellung.
- Rückerstattung einer offenen Einlösung.
- sicheres Löschen der Reward nach vorheriger Rückerstattung.
- automatische Rückerstattung ungültiger bzw. doppelter Medipaks.
- Persistenz der im Admin geänderten Reward-Einstellungen.
- Deaktivierung der automatischen Neuerstellung nach bewusstem Löschen.

Zusätzlich geprüft:

- Python-Bytecode-Kompilierung aller Backend-/Bridge-/Helper-/Test-Module: erfolgreich.
- JavaScript-Syntaxprüfung von `web/static/common.js` und allen vier Inline-Skripten via `node --check`: erfolgreich.
- Backend-Start mit Uvicorn: erfolgreich.
- HTTP-Smoke-Test gegen einen real gestarteten Backend-Prozess:
  - `/api/state` -> HTTP 200
  - `/challenge-overlay` -> HTTP 200
  - `/event-overlay` -> HTTP 200
  - `/dashboard` -> HTTP 200
  - `/admin` -> HTTP 200
  - `simulation_start` und `simulation_stop` über `/api/admin/action` -> HTTP 200
- Im echten HTTP-Smoke-Test wurde geprüft, dass OAuth-Tokens nicht im öffentlichen Twitch-State enthalten sind.
- Test-Suite enthält weiterhin HTTP/HTML-Smoke-Tests der Oberflächen und API via FastAPI TestClient.
- 5000-Hit-Stresstest für serverseitiges Boss-Damage-Tracking vorhanden und bestanden.

## Reale Twitch-Grenze

Ohne Anmeldung am Twitch-Konto konnten in der Build-Umgebung keine echten OAuth-Tokens erzeugt, keine echte Kanalbelohnung angelegt und keine echten Channel-Point-Redemptions verändert werden. Diese externen API-Aufrufe sind deshalb mit Fake-/Mock-Responses automatisiert getestet. Der lokale End-to-End-Pfad bis zum Twitch-Netzwerk sowie das Verhalten bei API-Fehlern sind implementiert; der erste reale Login geschieht auf dem Zielrechner über `Admin -> Mit Twitch anmelden`.

Die Integration gibt Twitch-Fehler wie fehlende Scopes, ungültige Tokens, fehlende Affiliate/Partner-Berechtigung oder eine Reward, die von einer anderen App erstellt wurde, im Adminbereich aus, statt einen erfolgreichen Zustand vorzutäuschen.

## Wichtige Sicherheits-/Hardwaregrenze

Der echte KICKR CORE 2 konnte in dieser Umgebung nicht physisch getestet werden. Deshalb wird kein erfolgreicher FE-C-Befehl vorgetäuscht. `TrainerControlService` implementiert Capability-Test, Grade 0/1/2, Restore, Fehlerzustand und Not-Aus hinter einer Adaptergrenze. `FakeTrainerAdapter` deckt die komplette Logik automatisiert ab. Für reale ANT+ FE-C-Steuerung ist `ExternalFECAdapter` vorgesehen; ein real validierter FE-C-Master-Helper wird über `BICYCLE_FEC_HELPER` angebunden. Der mitgelieferte `tools/fec_helper.py` bleibt absichtlich fail-safe und meldet ohne echten Control-Backend-Adapter "nicht kontrollierbar".

## Start unter Windows

1. `setup_windows.bat`
2. `BicycleStreamUI_TEST.bat` für den ersten Teststart oder `BicycleStreamUI.bat` für den Echtbetrieb.
3. `http://127.0.0.1:5050/admin` öffnen.
4. Im Bereich **Twitch Login & Medipak-Kanalbelohnung** auf **Mit Twitch anmelden** klicken und den Twitch-Login bestätigen.
5. Nach erfolgreichem Login wird die Medipak-Belohnung automatisch angelegt. Kosten/Titel/Prompt können direkt im Admin geändert werden.
6. Danach die OBS-Browser-Sources aus dem README eintragen.

Die Test-Startvariante sperrt die Persistenz synthetischer Bridge-Kilometer, damit Testdaten die echte Challenge nicht verändern.
