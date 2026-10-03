# BicycleStreamUI – Korrekturversion V6 (03.10.2026)

## Update installieren
Programm und OBS-Browserquellen stoppen. Alten Programmordner sichern.
Für ein Update die Ordner backend, web und tests sowie UPDATE_FIXES_V6.md
in die bestehende Installation kopieren und vorhandene Dateien ersetzen.
Eigene config, data, .env und gc_live.json behalten. Danach normal über
BicycleStreamUI.bat starten und OBS-Browserquellen aktualisieren.
Das ZIP enthält das vollständige Projekt inklusive der mitgelieferten
Konfiguration und des Datenstands aus dem hochgeladenen Original.
Eine lokale Python-Umgebung (.venv) lässt sich über setup_windows.bat erstellen.

## Sechs Korrekturen
1. Die automatische Anfrage nach offenen Medipak-Einlösungen nutzt keinen
   blockierenden Browser-Alert mehr. Fehler stehen direkt bei Twitch und in der
   Einlösungstabelle. Aktualisieren versucht es erneut. Der Fehler nennt nun
   den betroffenen Twitch-API-Aufruf; Twitch-Verbindung und Medipak-Abfrage
   haben getrennte Statusmeldungen. Der hochgeladene Log enthält zusätzlich
   einen gescheiterten automatischen Medipak-Anlegeversuch. Ob dessen Ursache
   ein lokales Netzwerkproblem oder Twitch war, lässt der alte Log nicht erkennen.
2. Nach einem beendeten SIM-Kampf erzeugen Emote Hit, Medipak und Rider Boost
   keinen weiteren Boss. Ein erster Testtreffer darf weiterhin einen ersten
   Testboss starten. Neue Kämpfe starten nach einem Ergebnis ausdrücklich per
   Small Boss, Major Boss oder Finalboss. Der tödliche Finalboss-Treffer löst
   CHALLENGE_FINALE aus und startet das bestehende 18-Sekunden-Feuerwerk.
3. Emote-Bilder fliegen erst nach erfolgreichem Laden. Bei Ladefehler oder
   mehr als vier Sekunden Wartezeit wird ein lokales Blitzsymbol verwendet.
   WebSocket-Nachrichten liefern den Kampfzustand vor den Treffer-Ereignissen,
   damit ein neuer Kampf nicht mit der alten Kampfkennung abgeglichen wird.
   Der tödliche Treffer kann den besiegten Boss für seine letzte Salve halten.
4. Im Balken steht durchgehend die Kilometerzahl (z.B. 1123.0 / 1000 km).
   Der Balken bleibt bei maximal 100 Prozent. Weiterhin Boss alle 20 km und
   Mega-Boss alle 100 km; nur der Boss exakt am Ziel ist der Finalboss.
   Nächste Kilometertermine und Boss-Vorwarnungen laufen über das Ziel hinaus.
   SIM übernimmt auch echte Kilometerstände über dem Ziel und erlaubt 1123 km.
5. Größerer Countdown mit leuchtendem Rahmen, Zeitbalken, Ziffernwechsel und
   lokalen Zwischenupdates. Ab 30 Sekunden gelb, ab 10 Sekunden rot/pulsierend.
   Bei niedrigen Bildschirmhöhen passt sich die Größe an.
6. Der erklärende Text unter dem aktiven Boss wurde entfernt. Die Anleitung
   vor dem Kampf bleibt in der Boss-Vorwarnung erhalten.

## Durchgeführte Prüfung
79 automatisierte Tests bestanden (python -m pytest -q).
Enthalten: Python-Funktions- und Integrationstests; Seiten/API-Smoketests;
WebSocket-Zustand vor Emote-Treffern; JavaScript-Syntax und DOM-Ziele;
Admin-Aktionsbindungen; Fehler beim automatischen Laden von Einlösungen ohne
Popup; verzögertes Emote-Bild vor Flugstart; Salven und Schadensanzeige;
Countdown-Warnstufen; tatsächlich erzeugte Feuerwerk-Partikel;
tödlicher Finalboss-Treffer plus acht weitere Treffer ohne neuen Boss;
SIM-Datenisolation; echte Distanzschwellen 1020/1100 km und volle Progressbar.

Grenzen: Frontend-Verhalten wurde in Node mit DOM-Simulation geprüft.
Ein zusätzlicher Playwright-Browsertest konnte nicht ausgeführt werden, weil
kein Browser verfügbar war und der Browserdownload in dieser Umgebung
scheiterte. Daher keine visuelle Prüfung in Chromium/OBS. Echter Twitch-Login,
Kanalbelohnungs-API und ANT+/Kickr-Hardware konnten hier nicht live geprüft
werden. Netzwerkfehler und Twitch-Ereignisse wurden mit Testdaten simuliert.
Eine Starlette/AnyIO-DeprecationWarning hat keinen Test fehlschlagen lassen.
