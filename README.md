# OVJECT in-app news feed (`OVJECT/feed`)

Static JSON that OVJECT apps read and draw as **one native card** (no WebView, no code).
GitHub Pages serves the root of `main`; `v1/` is the schema-v1 path.

**Everything is managed in this repository.** Edit a source file under `src/` (the GitHub web editor is
enough), commit, and the `feed` workflow validates it, regenerates `v1/`, commits the result as
`github-actions[bot]`, and Pages redeploys. Nobody needs a local clone to publish copy.

> **Status (2026-10-19): both items under `src/oryth/` are approved by JY** (`approval.gate: pass`; the four
> `needs_human` locale strings were read and accepted unchanged), so every file under `v1/` carries both items in
> its own language. CTA URLs are real: KAIRO leads to its App Store page, Oddside to the `ovject.com` home page
> until it has a pre-registration page of its own (then replace `cta.url` only; a new item id when the copy changes).
> Five more OVJECT app intros (`random-taptap`, `pitapato`, `croco-snap`, `croco-roulette`, `pitapato-field-day`,
> all `*-intro-2026w44`) sit in `src/oryth/` with `approval.gate: pending`, so they are **not published** yet
> (see "Current state").

## Layout

| Path | What | Who writes it |
|---|---|---|
| `src/<app>/<item-id>.json` | one item per file: shared fields, `strings.<locale>` for all ten locales, `approval`, per-locale gate results `review`, memos `notes` / `gate_context` | people |
| `src/_links/<app>.json` | `{"links": [...]}`: the link row of that app's OVJECT page (website, store, support, privacy, later socials); the same row goes into all ten locale files | people |
| `src/_hosts/<app>.json` | an app whose feed is derived from another app's approved items (e.g. KAIRO from Oryth); see "다른 앱의 항목을 그대로 쓰는 앱" | people |
| `clients/` | client kit for apps (spec, `test-vectors.json`, reference implementation, Swift and GDScript cores): take it and implement in your language | maintainers |
| `tools/build_feed.py` | validator + generator, standard library only (**canonical copy**) | maintainers |
| `tools/test_build_feed.py` | unit tests + the rules every item under `src/` must meet | maintainers |
| `tools/feed-schema.json`, `tools/fixtures/` | output schema (reference) and the example the tests use | maintainers |
| `v1/<app>/<locale>.json` | the published feed. **Generated: never edit by hand**, the workflow overwrites it | `github-actions[bot]` |
| `img/<app>/` | card images (rules in `img/oryth/README.md`) | people |
| `.github/workflows/feed.yml` | the pipeline | maintainers |

## GitHub에서 고치는 법 (how to edit on GitHub)

1. `src/<app>/<item-id>.json`을 열어 연필 아이콘으로 고친다: 문구는 `strings.<locale>`, 기간은 `starts_at`·`ends_at`, 링크는 `cta.url`(https + utm 4종). 문구를 바꾼 새 캠페인은 **새 id = 새 파일**(파일 이름 = id).
2. 공개 조건: `approval.gate`가 `pending`이 아니고 `approved_by`·`approved_at`이 채워진 항목만 나가고, `review.<locale>.gate`가 `pass`인 로케일 파일에만 들어간다(아니면 그 로케일에서만 빠진다, 영어 대체 없음). 앱은 자기 자신을 소개하지 않는다: `src/<app>/`의 항목이 `tags`에 `<app>`을 갖거나 id가 `<app>-`로 시작하면 검증 오류(JY 결정 2026-10-19).
3. "Commit changes": main에 직접 커밋하거나 새 브랜치 + PR. PR이면 Actions `feed`가 검사만 하고 요약(Summary)에 "무엇이 바뀔지" diff를 보여 준다.
4. main에 들어가면 Actions `feed`가 테스트·검증 → `v1/` 재생성 → `github-actions[bot]` 커밋 → Pages가 1분쯤 뒤 재배포. 빨간 ✗면 아무것도 공개되지 않고 마지막 정상 `v1/`이 그대로 남는다(로그의 `FAIL …` 줄이 이유).
5. 확인: Actions 탭 초록 ✓ + `https://ovject.github.io/feed/v1/<app>/<locale>.json`. 끄기: 항목 파일을 지우거나 `approval.gate`를 `pending`으로 바꾸면 그 항목이 빠진 피드가 올라간다(전부 빠지면 `items: []`).

## GitHub에서 링크 추가하는 법 (how to add a link)

1. `src/_links/<app>.json`을 열어 연필 아이콘으로 `links` 배열에 한 줄을 더한다: `{ "kind": "instagram", "url": "https://www.instagram.com/ovject.official/" }` (계정이 생기면 `kind`와 `url`만; 현재 소셜은 `ovject.official`의 Instagram·Threads, 보이는 순서는 배열 순서).
2. `kind`: `website`·`appstore`·`support`·`privacy`·`instagram`·`x`·`threads`·`youtube`·`discord`·`bluesky`·`tiktok`·`github`. `label`은 생략하면 영어 기본값(Website·App Store·…)이 들어간다. 최대 8개, 적은 순서대로 보이고, 같은 url 두 번은 안 된다.
3. 허용 호스트가 kind마다 정해져 있다(website·support·privacy는 `ovject.github.io`·`ovject.com`, appstore는 `apps.apple.com`, 소셜은 각 서비스 도메인). https만. 어긋나면 Actions가 빨간 ✗로 멈추고 아무것도 공개되지 않는다.
4. 커밋하면 Actions `feed`가 10개 로케일 파일 모두에 같은 `links`를 넣어 `v1/`을 다시 만든다. 링크는 항목 승인(`approval`)과 무관하게 바로 공개되고, 항목 UTM 규칙은 적용되지 않는다. 파일을 비우면(`"links": []`) 피드에서 `links` 필드가 빠진다.
5. 참고: 홈페이지 계열 링크(website·support·privacy)는 `ovject.com` 주소를 직접 쓴다(JY 결정; `ovject.github.io/Website/…`는 `ovject.com`으로 301이라 쓰지 않는다). 주소를 바꿀 일이 생기면 이 파일의 `url`만 고친다.

## 승인하는 법 (how to approve)

1. GitHub 웹에서 `src/<app>/<item-id>.json`을 열고 `approval`을
   `{"gate": "pass", "approved_by": "JY", "approved_at": "2026-10-20T09:00:00Z"}`처럼 바꾼다(`approved_at`은 ISO 8601 UTC).
2. `review`에서 `gate`가 `needs_human`인 로케일은 그 로케일의 `strings`를 직접 읽는다. 그대로 괜찮으면 `gate`를 `"pass"`로 바꾸고 사유를 `reasons`에 적는다. 아니면 `strings.<locale>`을 고친 뒤 `gate`를 `"pass"`로 바꾼다. `pass`가 아닌 로케일은 그 로케일 파일에서 항목이 빠진다(영어 대체 없음).
3. 커밋(main 직접 또는 PR 머지) → Actions `feed`가 `v1/`을 다시 만들어 봇 커밋 → Pages가 1분쯤 뒤 재배포.
4. **경고: 승인된 항목이 하나도 없으면 피드는 `items: []`라서 앱의 OVJECT 페이지가 빈 상태가 된다**(승인 전 push, 또는 모든 항목을 `pending`으로 되돌릴 때). Oddside의 CTA는 전용 사전등록 페이지가 생기기 전까지 `https://ovject.com/` 홈이다. 페이지가 생기면 `cta.url`만 바꾼다(문구가 바뀌면 새 id).

## 다른 앱의 항목을 그대로 쓰는 앱 (derived host, 예: KAIRO 갤러리 카드)

`src/_hosts/<app>.json`이 있는 앱의 피드는 부모 앱(`derive_from`)의 항목을 복사해 만든다. 새 앱 소개는 **`src/oryth/`에 한 번만** 등록하고 승인하면, 부모에서 승인된 항목이 파생 앱의 `v1/<app>/`에도 자동으로 들어간다(JY 결정 2026-10-20: 부모 승인이 파생 앱에도 적용). 문구·게이트 결과·승인은 부모 것을 그대로 쓴다.

```json
{ "derive_from": "oryth", "platforms": ["ios"], "min_app_version": "2.0.1",
  "max_impressions_per_user": 20, "cta_hosts": ["apps.apple.com", "ovject.com"], "exclude": [] }
```

| 필드 | 뜻 |
|---|---|
| `derive_from` (필수) | 부모 앱 슬러그. 부모가 또 파생 앱이면 안 된다 |
| `platforms` (필수) | 이 앱에서 항목을 보여 줄 플랫폼(부모의 `platforms`를 대체) |
| `min_app_version`, `max_impressions_per_user` | 있으면 부모 값을 대체 |
| `cta_hosts` | 있으면 CTA 호스트가 이 목록에 없는 항목은 뺀다(안드로이드 전용 Play 링크 등) |
| `exclude` | 가져오지 않을 항목 id |

- 항목의 `runs_on`(그 앱이 실제로 도는 플랫폼)이 있고 호스트의 `platforms`와 겹치지 않으면 뺀다: 데스크톱 전용 앱(`["macos"]`·`["windows"]`)은 KAIRO(iOS)에 나오지 않는다. `runs_on`이 없는 항목(예: 사전등록 페이지)은 그대로 들어간다. 새 앱 항목에는 `runs_on`을 꼭 적는다.
- 스토어 링크(App Store·Google Play)는 호스트 `platforms`에 맞게 `store`의 ID로 **다시 만든다**: `["android"]`면 `play.google.com/store/apps/details?id=<android_package>`, `["ios"]`·`["macos"]`면 `apps.apple.com/app/id<ios_app_id>`. 필요한 ID가 없는 항목은 빠진다. `["ios","android"]`처럼 둘을 함께 쓰는 호스트는 CTA가 `{"action": "store"}`가 되어 클라이언트가 실행 중인 플랫폼의 스토어를 연다. 웹·Threads 링크는 그대로.
- 앱 쪽 클라이언트(광고 실패 시 카드)를 만들 때는 `clients/README.md`와 `clients/test-vectors.json`을 가져가서 구현·검증한다.
- CTA의 `utm_source`는 파생 앱 슬러그로 바뀐다(`utm_content`는 항목 id 그대로).
- 파생 앱 자신을 소개하는 항목(`tags`에 앱 이름, id가 `<app>-`로 시작)은 조용히 빠진다.
- `src/<app>/<id>.json`을 따로 두면 같은 id의 부모 항목 대신 그 파일이 쓰인다(파생 앱만 문구를 다르게 하고 싶을 때).
- 부모 항목을 `pending`으로 되돌리면 파생 앱에서도 같이 빠진다.

## Pipeline (`.github/workflows/feed.yml`)

| Event | What runs |
|---|---|
| push to `main` touching `src/`, `tools/`, `v1/` or the workflow | job `check`, then job `publish` |
| pull request touching the same paths | job `check` only; the job summary shows the `v1/` diff that merging would publish |
| manual run (Actions → feed → Run workflow) | same as a push to `main`; use it to retry after a failure |

- `check`: `python3 -m unittest discover -s tools` → `tools/build_feed.py --skip-unchanged` (pending items dropped,
  locales whose gate is not `pass` left out, every rule in `tools/feed-schema.json` applied) →
  `tools/build_feed.py --check v1/*/*.json` (strict: a pending item in the output fails the run) → diff preview.
- `publish` (`main` only, `contents: write` on this job alone): rebuilds the same way, and when `v1/` differs
  from what is committed, commits it as `github-actions[bot]` and pushes to `main`. Pages redeploys from that push.
- Only `actions/checkout` and `actions/setup-python`, pinned to a commit. Python 3.12, standard library only.

### Why the workflow commits `v1/` itself (and the option we did not pick)

Two designs were compared:

| | **Bot commit on `main` (chosen)** | Fail the run when `v1/` is stale, a person regenerates locally |
|---|---|---|
| Editing from the GitHub web UI | works end to end | every copy change needs a clone + Python, which is what this setup removes |
| What a red run means | a real validation error | mostly "you forgot to regenerate", hiding real errors |
| `v1/` always equals `build(src/)` | enforced (a hand edit of `v1/` is rebuilt away on the next run) | only by discipline |
| Permissions | `contents: write` on one job, via the job token (no personal token stored) | read only |

Why the chosen design is safe:

- A push made with the job token never starts another workflow run, and the bot commit only touches `v1/`,
  so there is no loop; `--skip-unchanged` also means a rerun with nothing changed commits nothing
  (`generated_at` only moves when the content moves).
- `concurrency` serialises runs per branch, so two bot commits never race.
- Validation runs *before* anything is written; a failure publishes nothing and the last good `v1/` stays.
- Nothing is published that the generator would not produce from `src/`: no pending item, no locale whose gate
  did not pass, nothing over the size, count or length limits.

Known limits: the bot push needs `main` to accept direct pushes from Actions (no branch protection rule that
requires pull requests, or one that exempts the bot). The repository must have Actions enabled, with the
default "Read repository contents" token setting; the workflow raises its own permission to write for the
publish job. Pages stays on "Deploy from a branch" (`main`, `/`); if a bot push ever fails to trigger the Pages
deployment, the fallback is switching Pages to the Actions deployment (`actions/upload-pages-artifact` +
`actions/deploy-pages`), which this workflow does not use yet.

## Rules the build enforces

- An item is published only when `approval.gate` is not `pending` **and** `approved_by` is set; a `review.<locale>.gate`
  other than `pass` leaves the item out of that locale's file (no English fallback for a failed gate).
- An app never introduces itself: in `src/<app>/`, an item whose `tags` contain `<app>` or whose id starts with
  `<app>-` is a validation error for that app's feed (JY, 2026-10-19). The same item is fine in another app's folder.
- Two platform fields, not one: `platforms` (required) lists the **host app platforms on which the item is shown**
  (`ios`, `android`, `macos`; the host app hides the card when its own platform is absent). `runs_on` (optional) lists
  the **platforms the promoted app itself runs on** (`macos`, `ios`, `android`, `web`, `windows`) and is passed through
  to the output unchanged so the card can say where that app is available. Omit it while unconfirmed
  (KAIRO: `["ios"]`; Oddside: none yet).
- Each `strings.<locale>` is complete (`title`, `body`, `cta_label`, `secondary_label`) or absent; the tests require
  all ten locales for every committed item (OVJECT rule, 2026-10-19).
- Limits: title ≤ 40, body ≤ 120, labels ≤ 16 characters; HTTPS only; `cta.url` carries `utm_source=<app>`,
  `utm_medium=feedcard`, `utm_campaign`, `utm_content=<item-id>`; ISO 8601 dates with `ends_at` after `starts_at`;
  ≤ 10 items and ≤ 20 KB per file; no markup in text; `additionalProperties: false` everywhere.
- `notes`, `gate_context`, `review` and `strings` never reach the output. They stay in `src/` for traceability,
  but this repository is public: do not write anything there that must stay private.

## Local use

```bash
python3 tools/build_feed.py                                   # every app under src/ → v1/
python3 tools/build_feed.py --app oryth --include-pending     # preview unapproved items (do not commit)
python3 tools/build_feed.py --check v1/oryth/*.json           # lint existing files
python3 -m unittest discover -s tools -p "test_*.py"
```

## Marketing folder and the Nimble gate

The private marketing folder keeps a snapshot of the generator (`marketing/scripts/build_feed.py`) and a draft
area (`marketing/crosspromo/feed-src/<app>/`): night production writes drafts there, and `marketing/scripts/gate_feed.py`
runs the Nimble gate over every locale string and writes `review.<locale>` into the draft. **This repository's `src/`
is the source of truth for what is published**: copy a gated draft here (or edit here directly) to publish.
When the two differ, `src/` wins. Specification: `marketing/crosspromo/CROSS_PROMO.md` §8.

## URL rules

| What | URL |
|---|---|
| Feed | `https://ovject.github.io/feed/v1/<app>/<locale>.json` |
| Image | `https://ovject.github.io/feed/img/<app>/<item-id>-<w>x<h>.<png\|jpg\|webp>` |

- `<app>`: lowercase slug (`oryth` first; later `kairo`, `oddside`). A new app is a new folder `src/<app>/`;
  the workflow builds every folder it finds. Removing an app means deleting both `src/<app>/` and `v1/<app>/`.
- `<locale>`: `en`, `ko`, `ja`, `zh-Hans`, `zh-Hant`, `es`, `fr`, `de`, `th`, `vi` (10 files per app, always all 10).
  Apps fall back to `en.json` on 404.
- `v1` is the schema path. A breaking change opens `v2/`; `v1/` keeps being served.
- Response headers are GitHub's (`Cache-Control: max-age=600`, `ETag`); the real refresh period is the
  feed's `ttl_hours` (12).
- **Off switch**: a feed with `items: []` makes the card disappear from every app on its next refresh
  (delete the item files or set their `approval.gate` to `pending`).
- Only HTTPS. Keep `.nojekyll` so Pages serves files as-is. `src/`, `tools/` and `.github/` are served too; they
  contain nothing secret.
- Changed copy gets a **new item id** (apps store dismiss/impression state per id).

## Current state (2026-10-19)

- `src/oryth/`: `oddside-intro-2026w44`, `kairo-intro-2026w44`, all ten locales written by hand. **Approved by JY on
  2026-10-19** (`approval` = `pass` / `JY` / `2026-10-19T11:26:06Z`). The Nimble gate had passed 16 of 20 locale
  strings; the four `needs_human` ones (Oddside `en`·`th`·`vi`, KAIRO `th`) were read by JY and accepted unchanged
  (`review.<locale>.human`). CTA URLs: KAIRO → its App Store page (`apps.apple.com/app/id6745693309`), Oddside →
  `https://ovject.com/` until a pre-registration page exists. `kairo-intro` carries `runs_on: ["ios"]`; `oddside-intro` has no `runs_on`
  (release platforms unconfirmed).
- `src/oryth/` also holds five OVJECT app intros, **pending approval** (`approval.gate: pending`, so the default build
  leaves them out and `v1/` is unchanged): `random-taptap-intro-2026w44` (priority 4), `pitapato-intro-2026w44` (3),
  `croco-snap-intro-2026w44` (2), `croco-roulette-intro-2026w44` (1), `pitapato-field-day-intro-2026w44` (1). All ten
  locales are written by hand from the OVJECT website feed pages and the App Store / Google Play listings; no image,
  no figures, no promises. CTAs go to the App Store page (Field Day: Google Play only, `runs_on: ["android"]`).
  Nimble gate: 41 of 50 locale strings `pass`, 9 `needs_human` (Field Day `en`·`zh-Hans`·`es`·`fr`·`de`·`th`·`vi`,
  PITAPATO `vi`, Croco Snap `th`). **Approving means setting `approval` and also reading each `needs_human` locale
  and setting its `review.<locale>.gate` to `pass`; a locale left at `needs_human` simply omits that item.**
  **On hold (JY, 2026-10-19): `croco-snap-intro-2026w44` and `pitapato-field-day-intro-2026w44` are left out of the
  first approval**; keep them `pending` until their store descriptions are reconciled.
  Croco Snap!: the Google Play listing describes a different game (a beat-memory game) than the website and the App
  Store (crocodile roulette); the card follows the latter.
- `v1/oryth/*.json`: ten files, two items each (Oddside priority 10, KAIRO priority 5) plus the `links` row from
  `src/_links/oryth.json` (website, App Store developer page, support, privacy), the default build of the sources above.
- Published: the repository and Pages (`main`, `/`) exist since 2026-10-19 and serve whatever `main` holds.
