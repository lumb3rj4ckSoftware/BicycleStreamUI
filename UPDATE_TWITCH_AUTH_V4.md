# Twitch-Anmeldung – Korrektur V4

## Installation

1. Programm vollständig beenden und den bisherigen Ordner sichern.
2. Dieses Paket in einen neuen Ordner entpacken.
3. Den eigenen vollständigen Ordner `data`, die eigene `config/challenge_config.json` und gegebenenfalls die eigene `.env` aus der bisherigen Installation übernehmen. Dadurch bleiben Kilometerstand, Statistiken und Einstellungen erhalten. Keine Tokens in Nachrichten kopieren.
4. `BicycleStreamUI.bat` starten und das Adminmenü mit Strg+F5 neu laden.
5. Bei ungültiger Anmeldung auf **Mit Twitch anmelden** klicken und den eigenen Broadcaster-Account bei Twitch freigeben. Eine Token-Datei muss dafür nicht manuell gelöscht werden.

## Ursachen und Änderungen

`HTTP 401: Invalid OAuth token` bedeutet, dass Twitch den verwendeten Access Token zurückweist. Ob er abgelaufen oder widerrufen war, lässt sich allein aus dieser Meldung nicht entscheiden. Twitch-Aktionen verwenden dieselbe Anmeldung; daher können mehrere Aktionen gleichzeitig betroffen sein.

Der bisherige Code zeigte ungültige Tokens weiterhin als angemeldet an. Der Login-Button wird nach einer definitiven Ablehnung jetzt wieder freigegeben; Aktionen melden eine verständliche HTTP-401-Antwort statt eines internen HTTP-500-Fehlers.

Nach erfolgreichem Device-Code-Austausch werden neue Access- und Refresh-Tokens sofort gespeichert. Bei einem vorübergehenden Fehler der anschließenden Validierung bleibt die Anmeldung im Zustand „prüfe Verbindung“ und versucht die Prüfung erneut. Auch nach einem Neustart kann dieser Zustand abgeschlossen werden. Der bereits verbrauchte Device-Code wird nicht erneut eingelöst. Alte Account-IDs werden dabei nicht mit einem neuen Token kombiniert.

Leere Timeout-Ausnahmen, die vorher nur `OAuth validate:` ausgaben, zeigen jetzt den Fehlertyp und eine verständliche Erklärung. Aus dem alten leeren Text allein lässt sich die genaue Netzwerkursache nicht rekonstruieren. Die HTTP-Zeitgrenze beträgt bei OAuth-/Helix-Aufrufen jetzt 15 Sekunden.

Gleichzeitige HTTP-401-Antworten erneuern denselben abgelehnten Token nur einmal. Der neue Refresh Token wird gespeichert. Login-Polls und Abmeldung werden gegen überlappende Zugriffe geschützt. Das Adminmenü führt keine parallelen Login-Polls aus und kann laufende Anmeldungen nach einem Seitenneuladen fortsetzen.

EventSub versucht bei vorübergehenden Netzwerkproblemen erneut zu verbinden. Nach wiederhergestellter Anmeldung startet die Laufzeit einen zuvor beendeten EventSub-Task wieder. Token-Prüfungen erfolgen weiterhin mindestens stündlich; bevor ein bekannter Token abläuft, versucht die Wartung eine Erneuerung.

Die separate Warnung `Telemetry read failed: Expecting value ...` entsteht bei einer leeren oder unvollständigen JSON-Datei. Der Leser wiederholt solche Lesezugriffe zweimal nach jeweils 50 ms und merkt sich den Dateizeitstempel erst nach erfolgreicher Verarbeitung. Ein weiterhin defekter Datensatz wird weiterhin gemeldet und nicht verarbeitet.

## Prüfung

64 automatisierte Tests bestanden: bestehende Monster-/Finale-/Salven-Tests, JavaScript-Syntax und DOM-Smoke-Tests sowie neue Regressionen für Login-Timeout mit und ohne Neustart, parallele 401-Antworten, abgelehnte Tokens, verständliche Admin-Fehler, Hintergrundvalidierung und unvollständige Telemetrie-Dateien. Ein bestehender Starlette/AnyIO-Deprecation-Hinweis bleibt ohne Testfehler.

Die Twitch-Antworten wurden in den Tests simuliert. Ein echter Login mit deinem Twitch-Account, Live-Chat und OBS wurde hier nicht durchgeführt. Alle V3-Funktionen einschließlich der 20 Monster, des kompakten Sub-Overlays und des Abschlussfeuerwerks sind enthalten.

Offizielle Referenzen: https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/ und https://dev.twitch.tv/docs/authentication/refresh-tokens/
