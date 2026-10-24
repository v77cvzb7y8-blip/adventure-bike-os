# ROAM Foundation 03 – stabile Taschenverwaltung

## Ursachen und Korrektur

- Gegenstände (`packItems` bzw. `packProposal.items`) und Montagezustand wurden getrennt ausgewertet. Ein gespeichertes `saddle: false` konnte neben vier zugeordneten Gegenständen bestehen. Die Übersicht berechnete das Volumen trotzdem; der Explorer in `index.html` blendete die Tasche aus.
- Foundation 02 ignorierte diesen Widerspruch nur für „Meine Taschen“. „Taschen bearbeiten“ las weiterhin den falschen Montagewert. Der alte Detailrenderer verweigerte bei `mounted: false` das Rendern, ohne vorhandenes HTML zu leeren. Der Explorer las anschließend Überschrift und Gegenstandszeilen aus diesem versteckten, möglicherweise veralteten HTML. Damit konnten null Zeilen trotz befüllter Tasche angezeigt werden.
- Cargo-Helfer lagen in einer abgeschlossenen Funktion und waren für spätere Blöcke nicht erreichbar. Diese verwendeten deshalb abweichende Fallbacks und einen zweiten Montage-Speicher. Zusätzlich brach `renderPackNeed` (statt `renderPackNeeds`) die weitere Initialisierung dieses Blocks ab.

`pack-management.js` ersetzt den bisherigen Inline-Verwaltungsblock in beiden Seiten. `ROAMPack` stellt eine gemeinsame Sicht auf Definitionen, Größen, Montage und den aktiven Gegenstandssatz bereit. Zugeordnete, benötigte und vorhandene Gegenstände reparieren widersprüchliche Montageflags; explizit entfernte Taschen verlieren nach Bestätigung ihre Zuweisungen und bleiben entfernt. Leere, nicht montierte Taschen werden nicht allein durch einen Ansichtswechsel montiert.

`bag-explorer.js` rendert Inhalte direkt aus diesen Daten, ohne Zeilen aus einem versteckten Fenster auszulesen oder zu verschieben. Vorschauänderungen bleiben in der Vorschau, bis sie angewendet werden. Übersicht und Fahrrad verwenden denselben Zustand. Renderbenachrichtigungen ersetzen den bisherigen Explorer-MutationObserver. Die ältere automatische Detailöffnung und die ersetzten Cargo-Steuerungen wurden entfernt. Es wurde kein zusätzlicher Patchblock angehängt.

Das bestehende Explorer-Stylesheet ist in `bag-explorer.css` ausgelagert. Die Dialogbreite und die bereits vorhandene mobile Kopfzeilenregel wurden korrigiert. Das allgemeine Design und die übrigen Bereiche bleiben bestehen; root `index.html`, Backend und Deployment-Konfiguration wurden nicht geändert.

## Prüfung

Siehe [Testanleitung](README.md). Die Browserprüfungen verwenden synthetische Gegenstände mit exakt 4 Teilen / 5 von 14 Litern sowie 8 Teilen / 7,9 von 8 Litern und widersprüchlichen alten Montageflags. Die vier Kernprüfungen (zwei je HTML-Datei) scheitern auf dem unveränderten Ausgangsstand. Weitere Prüfungen betreffen alle drei Modi, leere Taschen, Verschieben, Kapazitätsgrenzen, Vorschau-Isolation, Entfernen mit Abbruch/Bestätigung, Neuladen, Tastaturbedienung, Cargo-Montage und mobile Dialogdarstellung.

Getestet wird in Headless-Chromium. Karten, Routing, Wetter, andere Browser und reale persönliche Speicherstände sind nicht Bestandteil dieser Tests. Es gibt keine vollständige Regression aller Reiseplanungsfunktionen. Die HTML-Seiten benötigen jetzt die drei benachbarten JS/CSS-Dateien; sie sind keine eigenständigen Einzeldateien mehr.
