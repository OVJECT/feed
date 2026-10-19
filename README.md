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
   (one file per item: shared fields + `strings.<locale>` + free `notes`).
2. Gate + approval: fill `approval.gate` (e.g. `nimble-5f-pass`), `approved_by`, `approved_at`.
   Items still `pending` are dropped by the default build.
3. Build into this clone:
   ```bash
   python3 /Volumes/SSD03/marketing/scripts/build_feed.py --app oryth --out /Volumes/SSD03/web/ovject-feed/v1
   ```
   `--include-pending` emits unapproved items for local preview only; rebuild without it before pushing.
4. Lint the written files (also runs inside the build):
   ```bash
   python3 /Volumes/SSD03/marketing/scripts/build_feed.py --check v1/oryth/*.json
   ```
5. Commit and push `main`; GitHub Pages redeploys in about a minute.
   Verify: `curl -sI https://ovject.github.io/feed/v1/oryth/en.json` → `200`, `content-type: application/json`.
6. Changed copy gets a **new item id** (apps store dismiss/impression state per id).

## Current state

`v1/oryth/*.json` was generated with `--include-pending` (2 items, approval pending, CTA URLs are placeholders:
the Oddside pre-registration page and a KAIRO page on ovject.com do not exist yet). Approve the copy, replace the
placeholder URLs in `feed-src`, rebuild without `--include-pending`, then push.

One-time setup (owner): create the public repo `OVJECT/feed`, enable Pages (branch `main`, path `/`), push this clone.
