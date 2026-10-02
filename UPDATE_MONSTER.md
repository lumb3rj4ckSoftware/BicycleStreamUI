# Monster-Update – Anleitung und Antworten

## Installation

1. Laufendes BicycleStreamUI und die zugehörigen Prozesse beenden.
2. Bestehenden Projektordner sichern. ZIP in einen neuen Ordner entpacken.
3. Falls vorhanden, `data/` und `.env` aus deiner bisherigen Installation in den neuen Projektordner übernehmen. Darin liegen Kilometer, Statistiken und Twitch-Anmeldung. Diese Dateien nicht durch leere Beispieldaten überschreiben.
4. Falls du eigene Einstellungen hast: `config/challenge_config.json` übernehmen. Die neuen Monster funktionieren auch mit der bisherigen Konfiguration.
5. `setup_windows.bat` ausführen und wie bisher mit `BicycleStreamUI.bat` oder `BicycleStreamUI_TEST.bat` starten.
6. OBS-Browserquellen aktualisieren (Cache der aktuellen Seite aktualisieren). Event-Overlay mit 1920 × 1080 verwenden. URLs bleiben gleich.

Vorschau aller 20 Monster: `web/static/monsters/gallery.html` öffnen oder nach dem Start `http://127.0.0.1:5050/static/monsters/gallery.html` aufrufen.

Die Monster sind bereits vollständig eingebunden. Kein manueller Eintrag im Code nötig. Der komplette Ordner `web/static/monsters/` gehört zur Installation.

## Was wurde geändert?

- 20 eigene generierte Fantasy-Monster statt der Kugel. Zufällige Reihenfolge; innerhalb eines Durchlaufs erscheint jedes Monster einmal.
- Die Bilder bewegen sich über CSS: Schweben, leichte Rotation, Größenänderung und Trefferreaktion. Das sind bewegte Einzelbilder, keine Animation mit einzeln gezeichneten Bewegungsphasen.
- Emotes fliegen vom unteren Bildschirmrand auf das Monster. Am Einschlag: Funken, Aufblitzen, Ruck und Schadenszahl.
- Alle unterschiedlichen erkannten Emotes einer Nachricht können mitfliegen; Twitch, 7TV, BTTV und zusätzlich FFZ. Kein vorgewähltes Kampf-Emote. Doppelte Emotes werden für die Darstellung zusammengefasst; maximal 12 verschiedene Bilder pro Nachricht.
- Schaden bleibt fair: ein Treffer pro Nachricht, 1 Damage bzw. 2 für Subs. Eine Nachricht mit 50 Emotes macht also nicht 50 Damage.
- 7TV/BTTV: globale und in deinem Kanal aktivierte Emotes. Es können nicht automatisch sämtliche Emotes aller fremden Kanäle erkannt werden. Drittanbieter-Emotes brauchen eine erreichbare API/CDN und den korrekten Kanal nach dem Twitch-Login. Animationen der Provider werden übernommen, soweit das Bildformat sie enthält.
- Meldungen während des Kampfs stehen in einer eigenen oberen Leiste. Monsterbild-Ladestatus und HP-Leiste sind getrennt.
- Challenge-Hintergrund wird mit steigender Geschwindigkeit kontinuierlich röter und brodelt schneller. Standard: Beginn bei 20 km/h, volle Intensität bei 40 km/h. Der Schalter Speed Heat deaktiviert die Hitze; Partikel haben einen eigenen Schalter.
- SIM-Modus verarbeitet jetzt echte Twitch-Chatnachrichten für den simulierten Boss, ohne Damage/Fights/Rewards in der echten Statistik zu speichern. Subs/Raids/Medipak aus dem echten Twitch-Kanal bleiben im SIM-Modus vom echten Ablauf getrennt; dafür die Testbuttons verwenden.
- Lokaler Chat-Test in der Adminseite funktioniert ohne Twitch-Anmeldung.
- Leere Chatnachrichten lösen keinen Fehler mehr aus. Twitch-Sendeablehnungen werden im Status angezeigt. Wiederholte Events nach WebSocket-Reconnect erzeugen keine doppelten Trefferanimationen mehr.

## Warum waren die HP so niedrig?

Es gab bereits Skalierung: Anzahl unterschiedlicher Chatter in den letzten 300 Sekunden, ausgewertet beim Spawn. Die HP steigen während des laufenden Kampfes nicht nachträglich. Später hinzukommende Chatter verändern also nicht die HP dieses Bosses. Die Zahl der Kampfteilnehmer und die für die HP verwendete Chatterzahl können unterschiedlich sein. Im Testlabor bestimmst du die Zahl über das Zahlenfeld; Standard ist 3.

| Chatter beim Spawn | Kleiner Boss | Großer Boss |
| --- | ---: | ---: |
| 0 | 35 HP | 100 HP |
| 1 | 47 HP | 125 HP |
| 3 | 71 HP | 175 HP |
| 10 | 155 HP | 350 HP |
| 20 | 275 HP | 600 HP |
| 50 | 635 HP | 1350 HP |

Formeln unverändert: klein `35 + 12 × Chatter` (max. 1200); groß `100 + 25 × Chatter` (max. 3000). Ein Sub verursacht 2 Damage je Nachricht. 150 bzw. 270 Sekunden sind das Zeitlimit; ausreichend viele Treffer können den Kampf deutlich früher beenden. Medipaks und Rider Assist verlängern weiterhin das Zeitlimit.

## Warum haben !km / !damage nicht geantwortet?

Im bisherigen Code brach `on_twitch_chat` im SIM-Modus sofort ab. Deshalb kamen keine Befehlsantworten und keine echten Chat-Treffer durch. Außerdem ist Twitch-Integration im ausgelieferten Standard zunächst ausgeschaltet. Ohne Anmeldung/Verbindung liest das Programm keinen Twitch-Chat.

Neu: Mit aktivierter Twitch-Integration und erfolgreicher EventSub-Verbindung funktionieren die Befehle auch im SIM-Modus. `!km` verwendet dann den simulierten Fortschritt. `!damage` und `!topdamage` zeigen mit [SIM] markierte Werte des Testkampfs; diese sind keine Lifetime-Statistik. Außerhalb der Simulation gelten die echten gespeicherten Werte. Es gilt weiterhin ein Cooldown von 8 Sekunden pro Befehl und Nutzer.

Ein laufender Videostream ist für Chatbefehle keine Voraussetzung. Wichtig sind Login, Berechtigungen, aktivierte Twitch-Integration/Chat Commands und eine bestehende EventSub-Verbindung. "Twitch verbunden" beschreibt die Chat-Verbindung, nicht den Live-Status deines Videos.

## Testablauf

1. Teststart ausführen, Adminseite öffnen, Simulation starten.
2. Chatter auf 1 oder 20 stellen, Small/Major Boss starten und HP vergleichen.
3. Emote Hit mit Kappa, LUL oder HeyGuys auslösen; optional Sub 2× aktivieren. Für 7TV/BTTV einen geladenen Global-/Kanalcode verwenden.
4. Im lokalen Chat-Test `!km`, `!boss` und `!damage` senden. Dort können auch erkannte 7TV/BTTV-Textcodes Treffer auslösen; reine Twitch-Codes ohne Twitch-Fragment-Metadaten bitte über Emote Hit testen.
5. Geschwindigkeit 30/35/40 einstellen und Challenge-Overlay beobachten.
6. Twitch anmelden, Twitch-Integration und Chat Commands aktivieren. Bei "Twitch verbunden" im Twitch-Chat Emotes und Befehle testen – auch während SIM.
7. Simulation stoppen: erst danach sind echte Kampfdaten und Lifetime-Werte aktiv.

## Prüfgrenzen

Automatische Backend-Tests und Browserprüfung sind im Prüfbericht dokumentiert. Ein echter Twitch-Account, ein realer Live-Stream und KICKR-Hardware standen für diese Prüfung nicht zur Verfügung. CDN/API-Laden von Drittanbieter-Emotes hängt zusätzlich von Internetverbindung und Provider-Verfügbarkeit ab.

Twitch-Dokumentation: https://dev.twitch.tv/docs/chat/send-receive-messages/ und https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types/#channelchatmessage
