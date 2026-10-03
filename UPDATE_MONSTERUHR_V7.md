# Monsteruhr V7 – 03.10.2026

Die Kampfzeit steht nun rechts oben neben dem Monster, innerhalb der
Monsterbühne. Sie ist deutlich kleiner, besitzt keinen Rahmen, keine
Beschriftung und keinen Zeitbalken mehr. Gezackter Eindruck durch schwere,
schräge Ziffern, Kerben und violette Schatten; Warnfarben bleiben erhalten.
Nur tatsächlich wechselnde Zeichen werden einzeln mit einem kurzen
Fall-/Drehimpuls animiert. Unveränderte Zeichen und Doppelpunkt bleiben
stehen. Bei reduzierter Bewegung werden Ziffern ohne Wechselanimation ersetzt.

Installation: Programm stoppen, den Ordner web aus diesem vollständigen ZIP
in die bestehende Installation kopieren und ersetzen. Eigene config und data
behalten. Anschließend neu starten und die OBS-Browserquelle aktualisieren.
Die vorherigen V6-Korrekturen sind enthalten.

Prüfung: 14 relevante Tests bestanden:
python -m pytest -q tests/test_frontend_syntax.py tests/test_finale_compact.py
Geprüft wurden JavaScript-Syntax/DOM-Ziele, Salven, Ziffernwechsel genau am
geänderten Zeichen, Minutenwechsel, keine erneute Animation beim gleichen
Zeitwert, Warnstufen, Sieg und Finalboss-Feuerwerk. Frontend-Verhalten wurde
mit DOM-Simulation in Node geprüft; keine visuelle Prüfung in OBS/Chromium.
