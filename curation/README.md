# Kurationsordner

Korrekturen und Ergänzungen an der zentralen Datenbank aus dem Editor (`nucdb editor`, Ziel
„Zentrale Datenbank“). Gleiches Dateiformat wie die Datenbank, plus `removals.json` für begründet
entfernte Einträge. Jeder Eintrag hat eine Quelle (Quellenpflicht).

`nucdb build` wendet diesen Ordner nach den Importern erneut an, damit Korrekturen einen
Neuaufbau aus den Rohdaten überstehen. Dateien nicht von Hand bearbeiten, sondern über den Editor
bzw. `nucdb.curation.Curation`.
