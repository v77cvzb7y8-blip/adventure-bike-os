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

---

# Foundation 03 review — 26 October 2026

Reviewed PR #1 at 151d1e2 and issue #3. PR is open/draft on
`codex/roam-foundation-03`; main at 2b26f19 is not a write target.
The existing head has a successful GitHub Actions run (40113094265).

## Next improvement

Dock open buttons previously invoked the legacy detail renderer, whose panel is
hidden by Explorer CSS. They now open the same Explorer as the bike, including
empty mounted bags in edit mode. Opening an unmounted dock bag no longer silently
mounts it; use its explicit Add action. Native buttons retain native Enter/Space
click synthesis; custom SVG handlers ignore repeated keydowns. Dialog Tab stays
inside, Escape/close returns focus, and prior body overflow is restored.
Tablet detail rows use one column; close/select targets are at least 44px high.

The original 18 browser cases are retained. Four additional cases cover both HTML
entry points: tablet touch/keyboard empty detail and mount persistence; route
preservation across pack interactions/reload and downloaded GPX coordinates,
elevation and XML escaping. This is an offline regression, not live routing QA.

## Remaining contradictions and gaps

- Issue test strategy names `roam-foundation-03-preview`; actual PR head is
  `codex/roam-foundation-03`. Continue on the PR head.
- In edit mode the bike SVG still toggles mounting; issue asks direct taps to open
  contents. Existing regression explicitly expects this toggle. Resolve together
  with updated bike interaction tests; dock details are now available independently.
- Fork artwork aggregates legacy fork/frontL/frontR, while its toggle only changes
  frontL/frontR. A stored legacy fork can stay visible after toggling the pair.
- Pair removal calls independent confirmations. Cancelling one can still remove the
  other. Atomic pair removal needs separate implementation and regression coverage.
- Display mode resets to used on reload; mounting/items persist, selected view does
  not. Clarify/fix before claiming full view-state persistence.
- No real-device Safari validation or personal legacy-storage validation yet.
- Local JS syntax and diff checks pass. Local npm test could not launch Chromium:
  browser download returned corrupt archives. CI is the browser validation gate.
