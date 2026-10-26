# ROAM Foundation 03 regression tests

Requires Node.js 20+ and a Chromium browser:

```sh
npm ci
npx playwright install chromium
npm test
```

For an already installed Chromium, use `BROWSER_EXECUTABLE_PATH=/path/to/chromium npm test`.
The suite starts its own local HTTP server and tests both `web-prototyp/index.html`
and `web-prototyp/ROAM_Foundation_02_Bike_Visibility_Test.html` in isolated browser contexts.
External requests are blocked deliberately; routing, weather and map-provider availability
are not validated. Fixtures use synthetic items with the reported counts and volumes,
including inconsistent legacy mounted flags. No personal browser data is required.

Coverage: saddle visibility and mounted status; frame contents; all three display modes;
empty mounted bags; moves and capacity checks; proposal isolation; cancel/confirm removal;
reload persistence; mobile width and Escape. Browser script errors fail the checked flows.

Additional detail regressions (22 tests total): 820px tablet viewport with touch,
empty mounted bag opened from the dock, native Enter/Space activation without
unmounting, dialog focus loop/return, empty mount persistence, and active route
preservation with downloaded GPX trackpoints/elevation/XML escaping. External
routing services and real iPad Safari remain outside this Chromium suite.
