# V5: Startstabilität und kompakte Sub-Übersicht

## Installation

1. Programm beenden und den bisherigen Ordner sichern.
2. V5 in einen neuen Ordner entpacken. Den bisherigen vollständigen Ordner `data`, die eigene `config/challenge_config.json` und gegebenenfalls `.env` übernehmen. Für den neuen Ordner `setup_windows.bat` ausführen, damit die lokale Python-Umgebung bereitsteht.
3. Normale oder Test-BAT starten. Adminseite mit Strg+F5 neu laden und OBS-Browserquellen aktualisieren.
4. Die kompakte Browserquelle bleibt `/sub-info-compact-overlay`. Empfohlene Größe: **460 × 170 Pixel**. Den Port der eigenen Installation verwenden, beispielsweise `http://127.0.0.1:5051/sub-info-compact-overlay`.

## Darstellung

Die große und die kompakte Übersicht teilen jetzt dieselbe CSS-Datei `web/static/sub-info.css`. Zahlkacheln, seitliche Farbakzente, Hintergründe, Rahmen und Schriftgrößen der Zeilen entsprechen einander. Im kompakten Overlay steht die Dauer groß rechts; unter dem Challenge-Namen steht klein:

- Sprint: Mehr Tempo für Stein!
- Steigung: Der Berg ruft.
- Stehend: Sprint im Stehen am Berg!

Oben bleibt nur „SUB → CHALLENGE“. Eine einzelne Zeile wechselt weiterhin alle fünf Sekunden mit einer vertikalen Animation. Die Zeiten und Steigungswerte werden weiterhin aus der Konfiguration übernommen.

## Was am Startablauf falsch war

Der alte Launcher wartete nur so lange, wie **beide** Unterprozesse liefen. Sobald Bridge oder Backend endete – auch mit Exit-Code 0 –, beendete er den anderen Prozess und gab selbst erfolgreich Exit-Code 0 zurück. Die eigentliche Ursache konnte dadurch unsichtbar bleiben. Der ANT-Scanner gab seine Ausgabe in eine Pipe aus; die Bridge wertete daraus nur Telemetrie aus und zeigte beispielsweise USB-/Dongle-Fehler nicht an.

Der Launcher verwendete außerdem unter Windows CTRL_BREAK für Prozesse, die ohne eine eigene Prozessgruppe gestartet worden waren. Prozessstart und gezieltes Stop-Signal passen jetzt zusammen: Jeder Dienst bekommt eine eigene Prozessgruppe. Das Abbruchsignal gilt beim bewussten Beenden nur dieser Gruppe. Unter POSIX werden eigene Sessions verwendet.

Aus dem gemeldeten Log allein lässt sich nicht bestimmen, welcher Prozess zuerst endete oder weshalb. Ein Twitch-Fehler ist darin nicht ausgewiesen. `^C` zeigt ein Abbruchsignal; es beweist keine fehlerhafte Twitch-Anmeldung.

## Neues Verhalten

- Bridge und Backend werden unabhängig überwacht. Bei einem unerwarteten Ende startet nur der betroffene Dienst nach 2, 4, 8, 16 und bei weiteren Fehlern höchstens alle 30 Sekunden neu. Der andere Dienst bleibt aktiv.
- Fehlgeschlagene Prozessstarts und Exit-Codes werden sichtbar protokolliert. Nach einem mindestens 60 Sekunden stabilen Lauf beginnt die Wartezeit wieder bei zwei Sekunden.
- Twitch-Anmeldung und Reward-Prüfung laufen beim Start im Hintergrund. Die Adminseite, Telemetrie und lokalen Overlays warten nicht auf Twitch. Verbindungsprobleme werden angezeigt; ein Loginfehler beendet den lokalen Server nicht.
- Die verschiedenen Auslöser für EventSub-Start/-Stop werden gegen Überlappung geschützt. Beim Herunterfahren werden die Aufgaben abgewartet und keine neuen Twitch-Aufgaben gestartet.
- Das Adminpanel wird vom Launcher erst geöffnet, wenn der lokale Server auf `/api/health` antwortet. Diese lokale Prüfung verwendet keinen externen Proxy.
- Der ANT-Scanner meldet sein unerwartetes Ende samt Exit-Code und den letzten Ausgabetexten. Dongle-/USB-/OpenANT-Fehler sind dadurch erkennbar. Bei einem Bridge-Neustart wird eine aktuelle ANT-Distanz wie bisher fortgesetzt.
- Ctrl+C beendet bewusst beide Dienste ohne automatische Neustarts. Die BAT zeigt einen fehlgeschlagenen Launcher-Start an und lässt die Fehlermeldung stehen.

## Diagnose-Dateien

- `data/launcher.log`: Prozessstarts, Exit-Codes, Neustart-Wartezeiten und bewusster Stop.
- `data/backend-output.log`: Backend-Konsolenausgabe einschließlich Startfehlern.
- `data/bridge-output.log`: Bridge-Fehler und Konsolenausgabe; laufende Distanzzeilen werden nicht dauerhaft gespeichert.
- `data/ant-scanner.log`: Scanner-Ausgabe ohne die laufenden Telemetrie-Datensätze.
- `data/bicyclestreamui.log`: bisheriges Anwendungsprotokoll.

Die zusätzlichen Logs rotieren ab 2 MiB und behalten drei Backups. Tokens werden nicht hinzugefügt.

## Prüfung und Grenzen

73 automatisierte Tests bestanden. Darunter: bestehende Monster-/Finale-/OAuth-Tests, JavaScript- und DOM-Prüfungen, getrennte Neustarts bei Exit-Codes 0/1/130, Startfehler-Wiederholungen, sichtbare Scannerfehler, nicht blockierende Twitch-Anmeldung und echte Bridge-/Backend-Neustarts in einem temporären Testprojekt. Ein vorhandener Starlette/AnyIO-Deprecation-Hinweis bleibt ohne Testfehler. Nach der letzten Scanner-Encoding-Anpassung wurden die neun Start-/Überwachungsprüfungen erneut erfolgreich ausgeführt. Der kompakte Stil wurde zusätzlich anhand eines statisch aus dem tatsächlichen JavaScript und CSS gerenderten Sprint-Elements kontrolliert. Das ersetzt keinen OBS-Browsertest. Die Linux-Prozessintegration und die Windows-Startflags werden geprüft; eine echte Windows-Konsole, der physische ANT-Dongle und der eigene Twitch-Account stehen hier nicht zur Verfügung.

Eine neue Prozessüberwachung behebt keine defekte USB-Verbindung oder widerrufene Twitch-Freigabe. Diese Ursachen werden jetzt isoliert und sichtbar. Bei einem vollständigen Backend-Prozessneustart verbinden sich die Overlays erneut; laufende, nur im Arbeitsspeicher gehaltene Kämpfe werden weiterhin nicht wiederhergestellt. Kilometerstand und Statistiken bleiben in `data` erhalten.

Referenzen: https://docs.python.org/3.10/library/subprocess.html und https://learn.microsoft.com/en-us/windows/console/console-process-groups
