# OVJECT in-app news feed (`OVJECT/feed`)

Static JSON that OVJECT apps read and draw as **one native card** (no WebView, no code).
Served by GitHub Pages from the repository root; `v1/` is the schema-v1 path.

- Spec: `marketing/crosspromo/CROSS_PROMO.md` §8 (private marketing folder)
- Schema: `marketing/crosspromo/feed-schema.json`
- Generator: `marketing/scripts/build_feed.py` (writes `v1/<app>/<locale>.json`)

## URL rules

| What | URL |
|---|---|
| Feed | `https://ovject.github.io/feed/v1/<app>/<locale>.json` |
| Image | `https://ovject.github.io/feed/img/<app>/<item-id>-<w>x<h>.<png\|jpg\|webp>` |

- `<app>`: lowercase slug (`oryth` first; later `kairo`, `oddside`).
- `<locale>`: `en`, `ko`, `ja`, `zh-Hans`, `zh-Hant`, `es`, `fr`, `de`, `th`, `vi` (10 files per app, always all 10).
  Locales without their own copy carry the English strings (the generator falls back to `en`; no machine translation).
  Apps fall back to `en.json` on 404.
- `v1` is the schema path. A breaking change opens `v2/`; `v1/` keeps being served.
- Response headers are GitHub's (`Cache-Control: max-age=600`, `ETag`); the real refresh period is the
  feed's `ttl_hours` (12). Files stay under 20 KB and 10 items.
- **Off switch**: publish `"items": []` and the card disappears from every app on its next refresh.
- Only HTTPS. Keep `.nojekyll` so Pages serves files as-is.

## Publishing procedure (a person pushes; agents never push)

1. Edit or add items in `marketing/crosspromo/feed-src/<app>/<item-id>.json`
   (one file per item: shared fields + `strings.<locale>` for **all ten locales**, written by hand, no
   translation engine + free `notes` + `gate_context` evidence). A locale is either fully written or absent;
   only an absent locale falls back to `en`.
2. Gate every locale string (serial Nimble calls, one per string):
   ```bash
   python3 /Volumes/SSD03/marketing/scripts/gate_feed.py --app oryth
   ```
   It writes `review.<locale>.gate` (`pass` / `fail` / `needs_human`) into the source file. A locale whose gate
   is not `pass` is **left out of that locale's file** (no `en` fallback). A human who reads a `needs_human`
   string and accepts it sets its `gate` to `pass` by hand (note why in `reasons`) or rewrites the string and
   runs the gate again.
3. Approval: fill `approval.gate` (e.g. `nimble-5f-pass`), `approved_by`, `approved_at`.
   Items still `pending` are dropped by the default build.
4. Build into this clone:
   ```bash
   python3 /Volumes/SSD03/marketing/scripts/build_feed.py --app oryth --out /Volumes/SSD03/web/ovject-feed/v1
   ```
   `--include-pending` emits unapproved items for local preview only; rebuild without it before pushing.
5. Lint the written files (also runs inside the build):
   ```bash
   python3 /Volumes/SSD03/marketing/scripts/build_feed.py --check v1/oryth/*.json
   ```
6. Commit and push `main`; GitHub Pages redeploys in about a minute.
   Verify: `curl -sI https://ovject.github.io/feed/v1/oryth/en.json` → `200`, `content-type: application/json`.
7. Changed copy gets a **new item id** (apps store dismiss/impression state per id).

## Current state

`v1/oryth/*.json` was generated with `--include-pending` (2 items, approval pending, CTA URLs are placeholders:
the Oddside pre-registration page and a KAIRO page on ovject.com do not exist yet). All ten locales are written
in `feed-src`; the Nimble gate passed 16 of the 20 locale strings and flagged 4 for human review
(Oddside `en`·`th`·`vi`, KAIRO `th`), so those are left out: `en.json` and `vi.json` carry only KAIRO,
`th.json` is empty (`items: []`, the app shows nothing). No locale string is approved by a person yet.
Review the flagged strings, approve the copy, replace the placeholder URLs in `feed-src`, rebuild without
`--include-pending`, then push.

One-time setup (owner): create the public repo `OVJECT/feed`, enable Pages (branch `main`, path `/`), push this clone.
