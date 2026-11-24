"""Importer für Primärquellen (nur für die Pflege der zentralen Datenbank).

Jeder Importer liest die Originaldateien einer Quelle unverändert ein und ersetzt in der
Datenbank alle Datensätze dieser Quelle. Ein Import lässt sich also beliebig oft wiederholen.
Werte anderer Quellen und manuelle Korrekturen (Quelle ``manual``) bleiben erhalten.
"""
