# V3 – Kompakte Sub-Anzeige und October1000-Finale

## Installation

Programm beenden und bestehenden Ordner sichern. ZIP in einen neuen Ordner entpacken. Deinen bisherigen `data/`-Ordner, `.env` und eigene `config/challenge_config.json` übernehmen. Dadurch bleiben Kilometer, Statistiken, Twitch-Anmeldung und eigene Emote-/Boss-Einstellungen erhalten. Keine neuen Abhängigkeiten und keine Datenbankmigration nötig. OBS-Browserquellen anschließend über „Cache der aktuellen Seite aktualisieren“ neu laden.

## Zweites Sub-Info-Overlay

Neue separate Browserquelle: `http://127.0.0.1:5051/sub-info-compact-overlay` (bei Port 5050 die Adresse entsprechend ändern). Empfohlen **360 × 150 px**, Hintergrund transparent.

Gleiche Farben und Kartenoptik wie die große Sub-Übersicht, aber nur Überschrift **SUB → CHALLENGE** und eine Zeile. Alle fünf Sekunden Wechsel in der Reihenfolge:

- 5 → Sprint (+30 Sekunden)
- 10 → 1 % Steigung (90 Sekunden)
- 15 → 2 % + stehend (90 Sekunden)

Die aktuelle Zeile gleitet nach oben aus, die nächste kommt von unten. Die kurze Zeitangabe und Steigungswerte stammen weiterhin aus deiner Konfiguration. Die Anzeige bleibt eine Übersicht der Gift-Pakete, keine neue kumulierte Sub-Zählung. Bei deaktivierten Sub-Challenges wird sie abgeblendet. Die große Version unter `/sub-info-overlay` bleibt erhalten. Beide Varianten sind im Adminbereich verlinkt.

## Deutlicher Boss-Timer und Sieg

Eigener Timerblock mit **76 px großer MM:SS-Anzeige**, dunklem Hintergrund, Leuchtrand und Beschriftung „VERBLEIBENDE ZEIT“. Letzte 30 Sekunden gelb, letzte 10 Sekunden rot und pulsierend. Bei einem Sieg springt die Anzeige auf **SIEG!**. Die zentrale Meldung **MONSTER BESIEGT!** ist ebenfalls deutlich größer und grün hervorgehoben. Eine Niederlage zeigt „ZEIT ABGELAUFEN“.

## Finalboss bei 1000 km

Beim Erreichen des Challenge-Ziels (standardmäßig 1000 km) startet der große Finalboss. Er verwendet die im Adminbereich gespeicherte Basiszeit für große Bosse sowie die vorhandene HP-Skalierung, Rider Assist und Medipaks.

Die Abschlussfeier beginnt **erst nach seinem Sieg**, nicht schon beim Überschreiten von 1000 km. Läuft bei Erreichen der Zielmarke noch ein anderer Kampf, wartet der Finalboss bis zu dessen Ende. Der Finalboss ist auch dann vorhanden, wenn eigene Bossintervalle die Zielmarke nicht genau treffen.

Nach dem Sieg: großes, bildschirmfüllendes Canvas-Feuerwerk mit aufsteigenden Raketen, farbigen Explosionen und Glitzerpartikeln. Die Show läuft etwa **18 Sekunden**, mit großer Abschlussmeldung **OCTOBER1000 GESCHAFFT!** und Dank an alle. Einzelne Partikel klingen danach kurz aus. Es ist keine weitere OBS-Quelle nötig: alles läuft im vorhandenen `/event-overlay` (1920 × 1080).

Nur ein Sieg des Finalbosses löst die Show aus. Normale Boss-Siege und eine Niederlage des Finalbosses erzeugen kein Abschlussfeuerwerk. Bosskämpfe und zentrales Event-Overlay müssen aktiviert sein. Echte Finalboss-Siege werden im Challenge-State vermerkt, damit dieselbe Abschlussfeier nicht mehrfach durch erneute Ergebnisverarbeitung ausgelöst wird. Die Kilometeranzeige kann bereits 1000/1000 anzeigen, während der letzte Kampf noch läuft.

Wie zuvor werden laufende Kämpfe bei einem Programmneustart nicht vollständig wiederhergestellt; vor dem Finalkampf deshalb möglichst keinen Neustart durchführen. Ein verlorener Finalboss wird nicht automatisch neu gestartet.

## Test ohne echte Kilometer / Statistik

Im Adminbereich **1000-km-Finalboss testen** drücken. Dadurch startet die Simulation mit 100 % Fortschritt und dem großen Finalboss. Emotes testen, dann im Boss-Testlabor **Win** drücken: das zeigt Feuerwerk und Abschlussmeldung. **Loss** zeigt die Niederlage ohne Feuerwerk. SIM-Versuche verändern weder echte Kilometer noch echte Boss-Statistiken oder den echten Abschlussvermerk.

## Prüfbericht

**56 Tests erfolgreich** (`python -m pytest -q`). Darunter bestehende Backend-, API-, Auth-, Statistik- und Emote-Salventests sowie neue Prüfungen für Finalboss beim Ziel, keinen vorzeitigen Abschluss, Finalboss bei abweichenden Intervallen, Warten auf den vorherigen Kampf, kein Feuerwerk bei Niederlage/normalem Sieg, Ergebnis-Deduplizierung und isolierte SIM-Tests.

Frontend: Syntax und DOM-Ziele beider Sub-Overlays geprüft. Kompakt-Modul in DOM-Stubs ausgeführt: Reihenfolge 5/10/15, Wechsel alle fünf Sekunden, eine Zeile nach Abschluss der Animation und aktuelle Konfigurationswerte. Event-Modul ausgeführt: Timerformat, kritische Warnfarbe, Siegmeldung, SIEG!-Timer und erzeugte Feuerwerk-Partikel geprüft.

Kein vollständiger Browser-/OBS-Layouttest und kein echter Twitch-/KICKR-Hardwaretest. DOM-Stubs prüfen keine reale CSS-Darstellung. Eine bestehende Starlette/AnyIO DeprecationWarning, kein Testfehler. Frühere Prüfberichte beschreiben die jeweiligen Vorversionen.
