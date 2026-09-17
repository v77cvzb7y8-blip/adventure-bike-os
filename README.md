# Adventure Bike OS — Web MVP

**Von der Inspiration zur fertigen Bike-Reise.**

Dieser erste Web-Prototyp konzentriert sich auf die wichtigste technische Kette:

1. Start und Ziel eingeben
2. Orte geocodieren
3. echte Fahrradroute berechnen
4. Route auf Karte anzeigen
5. Distanz und Höhenprofil auswerten
6. Etappen anhand Ziel-km/Tag und max. HM/Tag ableiten

## Testfall
Brixen, Südtirol → München · 150 km/Tag · max. 2.000 HM/Tag.

## Veröffentlichung über GitHub Pages
Alle Dateien in die oberste Ebene des Repositories `adventure-bike-os` hochladen.
Danach in GitHub: **Settings → Pages → Build and deployment → Deploy from a branch → main / root → Save**.

## Dienste im MVP
- OpenStreetMap-Karte
- Nominatim für die vom Nutzer ausgelöste Ortssuche
- BRouter für Fahrradrouting und Höhendaten

Nominatim wird nur nach Klick des Nutzers angesprochen; die beiden Ortsabfragen sind absichtlich um mehr als eine Sekunde getrennt. Für ein späteres öffentliches/kommerzielles Produkt sollte Geocoding und Routing über eine eigene bzw. vertraglich geeignete Infrastruktur laufen.

## Nächste Produktstufen
Terrain-/Technik-Check, Rider Fit, Bike Fit, Gravel-Anteil, Wasser/Food, Unterkünfte, Wetter, Packliste, Navigation/offline, Rücktransport und Kosten.
