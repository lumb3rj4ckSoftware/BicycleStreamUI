# Update V2 – Emote-Salven, Bosszeiten, Vorwarnung und Sub-Info

## Installation

Programm beenden, bestehenden Ordner sichern und ZIP in einen neuen Ordner entpacken. Deinen bisherigen `data/`-Ordner und gegebenenfalls `.env` übernehmen, damit Kilometer, Damage-Statistiken und Twitch-Login erhalten bleiben. Eigene `config/challenge_config.json` ebenfalls übernehmen: fehlende neue Emote-Einstellungen erhalten automatisch Standardwerte. Bestehende Start-BATs und URLs bleiben gültig.

OBS-Browserquellen anschließend über „Cache der aktuellen Seite aktualisieren“ neu laden.

## Emote-Salven

Jedes erkannte Emote-Vorkommen bleibt erhalten, auch zehnmal Kappa in einer Nachricht. Die Nachricht erzeugt eine Salve: gleiche Startposition und gleiche gerade Flugbahn, alle Emotes kurz hintereinander in ursprünglicher Reihenfolge. Twitch, 7TV, BTTV und FFZ bleiben unterstützt.

Gameplay: unverändert ein Treffer je Nachricht, 1 Damage bzw. 2 für Subs. Nur das erste Emote zeigt die Schadenszahl. Alle weiteren erzeugen lediglich Funken und Trefferreaktionen. Der Server zählt Damage weiterhin beim Empfang der Nachricht; das Overlay zeigt ihn am ersten Einschlag. Eine Salve mit zehn Kappas verursacht also keinen zehnfachen Schaden.

Standard-Flugzeit: 1,4 Sekunden, vorher 0,68 Sekunden. Startabstand: 130 ms bei 100 %. Im Adminbereich unter **Emote-Salven & Bosszeiten**:

- Größe: 24–160 px, Standard 58 px.
- Geschwindigkeit: 50–200 %, Standard 100 %. 50 % = ca. 2,8 Sekunden; 200 % = ca. 0,7 Sekunden.
- **Einstellungen speichern** drücken. Die Werte bleiben nach Neustart erhalten. Neue Salven verwenden die gespeicherten Werte; bereits fliegende Emotes behalten ihre Werte.

Alle Emotes einer Nachricht werden verarbeitet; die frühere Begrenzung auf zwölf verschiedene Bilder entfällt. Bei sehr hoher Last werden zusätzliche Projektile zeitversetzt gestartet, statt sie wegzulassen. Bis zu 200 Bilder können gleichzeitig fliegen. Nach dem letzten tödlichen Treffer bleibt das Monster für die restliche Darstellung der Salve kurz sichtbar; der Kampf gilt serverseitig bereits als gewonnen. Beim Wechsel zu einem neuen Kampf enden alte Salven.

Testlabor: Im Emote-Feld beispielsweise `Kappa Kappa Kappa LUL` eingeben und **Emote Hit** drücken. Der lokale Chat-Test unterstützt weiterhin Drittanbieter-Textcodes; Twitch-native Emotes dort über den Emote-Hit-Button testen, da lokaler Text keine Twitch-Emote-Metadaten enthält.

## Boss-Basiszeiten

Im selben Adminbereich sind separate Zeiten für kleine und große Bosse verfügbar, jeweils 1–3600 Sekunden. Standard bleibt 150 / 270 Sekunden. Speichern wirkt auf **neu gestartete Kämpfe**, auch im SIM-Modus. Ein laufender Kampf behält sein Zeitlimit. Medipaks und Rider Assist verlängern es weiterhin zusätzlich. HP und Damage-Skalierung bleiben unverändert.

## Vorwarnung

Im vorhandenen Event-/Monsteroverlay erscheint ab **500 Metern vor der nächsten Bossmarke** ein zentrierter Hinweis, dass ein Monster kommt und mit Chat-Emotes bekämpft werden muss. Der Text bleibt bis zum Kampfstart sichtbar; die verbleibenden Meter werden aktualisiert.

Beispiele: 19,5 km → Boss bei 20 km; 99,5 km → Mega-Boss bei 100 km. Die Warnung verwendet den Gesamtstand der Oktober-Challenge, nicht nur die aktuelle Trainingsdistanz. Sie funktioniert auch bei Neustart innerhalb des Warnbereichs sowie im SIM-Modus. Keine Warnung bei abgeschalteten Bosskämpfen, laufendem Boss oder bereits erledigter Bossmarke.

Im Adminbereich **500-m-Vorwarnung testen** drücken, um sie ohne Kilometeränderung in der echten Challenge zu sehen. Der Button schaltet in Simulation und beendet einen eventuell laufenden Testboss.

## Neues Sub-Info-Overlay

Neue OBS-Browserquelle: `http://127.0.0.1:5050/sub-info-overlay`, empfohlen **460 × 340 px**. Bei deinem Port 5051 entsprechend `http://127.0.0.1:5051/sub-info-overlay`. Hintergrund transparent, Stil passend zu den anderen Overlays.

Anzeige: 5 Gift-Subs → Sprint +30 s; 10 → 1 % Steigung für 90 s; 15 → 2 % Steigung und Sprint im Stehen für 90 s. Werte kommen aus der bestehenden Konfiguration. Aktive Challenges bzw. frisch eingetroffene Gift-Events werden hervorgehoben. Weitere 5er-Geschenke verlängern einen laufenden normalen Sprint. Die vorhandene Behandlung höherer Gift-Pakete bleibt unverändert. Es geht um einzelne Gift-Pakete, nicht eine neue aufsummierte Sub-Zählung.

## Neuer Chatbefehl

`!october1000` listet die Befehle dieses Programms samt Kurzbeschreibung: `!km`, `!heute`, `!plan`, `!next`, `!boss`, `!damage`, `!topdamage` und `!october1000`. Funktioniert über Twitch sowie im lokalen Chat-Test. Bestehender Cooldown und Twitch-Berechtigungen bleiben gültig. SIM-Antworten werden weiterhin mit [SIM] markiert.

## Prüfung

**49 Tests bestanden.** Bestehende Backend-, API-, Persistenz- und Auth-Tests sowie neue Tests für wiederholte/mischte Emotes, einzelne Damage-Zählung, Einstellungen und ihre Speicherung, Basiszeiten ab dem nächsten Kampf, Warnbereich, SIM-Warnung, Hilfe-Befehl und neue Overlay-Route.

Frontend: JavaScript-Syntax und statische DOM-Ziele geprüft. Admin-Modul mit DOM-Stubs ausgeführt: neue Einstellungen und Vorwarnungsbutton lösen die richtigen Aktionen aus. Salvenmodul ebenfalls ausgeführt: zehn Emotes, identische Flugbahn, gewählte Größe und Flugzeit, exakt eine Damage-Anzeige.

Kein vollständiger Browser-/OBS-Test: Browser-Binary fehlte und der Download war nicht verfügbar. DOM-Stubs prüfen weder die tatsächliche Darstellung noch echte Bildlade-/Animationseigenschaften. Kein Test mit echtem Twitch-Account oder KICKR-Hardware. Eine bestehende Starlette/AnyIO-DeprecationWarning, kein Testfehler.

Die vorherigen Prüfberichte beschreiben ältere Versionen. Für diese Ergänzung gilt dieser Abschnitt.
