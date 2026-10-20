# 앱 쪽 클라이언트 키트 (house ad 카드)

OVJECT 앱이 광고(AdMob 등)가 실패했을 때 같은 자리에 **OVJECT 앱 소개 카드 1개**를 보여 주는 클라이언트를 만들 때 쓴다. 공용 라이브러리를 배포하지 않고, **각 앱이 이 키트의 규칙과 테스트 벡터를 가져가서 자기 언어로 구현**하는 방식이다(복사해서 쓰기).

| 파일 | 역할 |
|---|---|
| `test-vectors.json` | **정답표.** 로케일 18, URL 안전 13, 버전 비교 7, CTA 해석 6, 항목 선택 33 = 77개 케이스. 어떤 언어로 구현하든 전부 맞아야 한다 |
| `reference.py` | 읽기 쉬운 참조 구현(= 규칙을 코드로 쓴 명세). 의문이 생기면 이 파일이 기준 |
| `swift/OvjectHouseAdCore.swift` | Swift 순수 로직(KAIRO 앱이 쓰는 파일과 **같은 내용**). UIKit 의존 없음. 그대로 복사해 쓸 수 있다. iOS 전용 호스트용이라 `action: store`(CTA 해석)는 구현하지 않았다 |
| `swift/main.swift` | Swift 코어를 벡터로 검증하는 실행기(호스트가 `kairo`·`ios`인 케이스만 비교) |
| `gdscript/ovject_house_ad_core.gd` | GDScript(Godot 4) 순수 로직: 로케일·URL 안전·버전·**CTA 해석(`store` 포함)**·항목 선택. Croco Roulette 앱이 쓰는 파일과 **같은 내용**, 그대로 복사해 쓴다 |
| `gdscript/vectors_test.gd` | GDScript 코어를 벡터 전체로 검증하는 실행기(`godot --headless --script clients/gdscript/vectors_test.gd -- clients/test-vectors.json`) |
| `../tools/test_clients.py` | 참조 구현, Swift 코어(swiftc가 있을 때), GDScript 코어(godot이 있을 때)가 벡터와 일치하는지 검사 |

Kotlin(안드로이드)·Dart 등은 아직 없다(GDScript는 Croco Roulette). 규칙 5절을 읽고 구현한 뒤 `test-vectors.json`을 읽는 단위 테스트를 붙이면 같은 기준으로 검증된다. 만든 포팅은 이 폴더에 `clients/<언어>/`로 넣어 두면 다음 앱이 가져간다.

## 1. 새 앱에 붙이는 순서

1. 피드 쪽: `src/_hosts/<앱슬러그>.json` 추가(아래 2절). 오리스에 등록·승인된 항목이 자동으로 들어온다.
2. 앱 쪽: 아래 3~5절을 구현하고 `test-vectors.json` 단위 테스트를 통과시킨다.
3. 광고 SDK의 **로드 실패(재고 없음·차단·네트워크 포함) 확정 신호**에 카드를 연결한다. 로딩 중에는 카드를 먼저 보이지 않는다(깜빡임).
4. **구독자(광고 제거 사용자)에게는 광고도 카드도 보이지 않게** 한다. 구독 상태가 판정되기 전에는 광고 로드·카드 요청을 보류한다.
5. 실기기에서 확인한다(광고 성공 → 카드 없음, 실패 → 카드, 탭 → 스토어/웹).

## 2. 피드 쪽 호스트 설정 (`src/_hosts/<앱슬러그>.json`)

```json
{ "derive_from": "oryth", "platforms": ["android"], "min_app_version": "1.0.0",
  "max_impressions_per_user": 20, "cta_hosts": ["play.google.com", "ovject.com", "www.threads.com"], "exclude": [] }
```

- **앱슬러그**는 그 앱을 소개하는 항목의 `tags`/id 접두사와 같아야 자기 자신 제외가 동작한다(예: `random-taptap`, `croco-roulette`, `pitapato`, `kairo`). 소문자·숫자·`-`, 2~32자.
- `platforms`: 이 앱이 도는 플랫폼 하나(`ios`, `android`, `macos`). 그 플랫폼에서 도는 앱(`runs_on`)만 들어온다.
  - 스토어 링크는 호스트 플랫폼에 맞게 **자동으로 다시 만든다**(Android 호스트 → Google Play `id=<패키지>`, iOS·macOS 호스트 → App Store `id<번호>`, UTM의 `utm_source`는 앱슬러그). 필요한 스토어 ID(`store.android_package` / `store.ios_app_id`)가 없는 항목은 빠진다. 웹사이트·Threads 같은 링크는 그대로.
  - 한 앱이 iOS와 Android를 함께 쓰는 단일 피드(`["ios","android"]`)라면 스토어 링크는 `{"action": "store"}`가 되고, 클라이언트가 `store` 정보로 실행 중인 플랫폼의 스토어를 열어야 한다(오리스 Dart 구현이 하는 방식, GDScript 코어의 `resolve_cta`도 그렇게 한다). 그 플랫폼의 스토어 ID가 없는 항목(예: Android 패키지가 없는 iOS 전용 앱)은 클라이언트가 건너뛴다. `action: store`를 구현하지 않은 클라이언트는 호스트를 플랫폼별로 나눈다.
- `cta_hosts`: 이 앱이 열 수 있는 주소의 호스트. 앱 쪽 허용 목록과 **같아야** 한다(아래 5절).
- 파일을 만들면 `python3 tools/build_feed.py`가 `v1/<앱슬러그>/<locale>.json` 10개를 만든다.

## 3. 요청·캐시 (모든 앱 공통)

- URL: `https://ovject.github.io/feed/v1/<앱슬러그>/<locale>.json`. HTTPS만, 요청 제한 시간 3초, `ETag`/`If-None-Match`(304이면 캐시 시각만 갱신).
- 캐시: 받은 본문과 시각을 저장하고, 피드의 `ttl_hours`(기본 12) 안에서는 다시 받지 않는다. 형식이 틀린 파일·`schema_version != 1`·`app`/`locale` 불일치는 버리고 이전 캐시를 쓴다. 실패해도 조용히(광고 자리는 빈 여백).
- 사용자별 기록을 서버로 보내지 않는다. 노출 횟수는 기기 로컬에만 저장한다.
- 원격 끄기: 피드의 `items`가 빈 배열이면 카드는 나오지 않는다.

## 4. 로케일

기기(또는 앱별 언어 설정) 언어를 10개 중 하나로 맞춘다: `en ko ja zh-Hans zh-Hant es fr de th vi`. 중국어는 `Hant`/`-TW`/`-HK`/`-MO`면 `zh-Hant`, 나머지 `zh*`는 `zh-Hans`. 지원 밖 언어는 `en`. 정답은 `test-vectors.json`의 `locale`.

## 5. 항목 선택 규칙 (정답은 `reference.py`와 `pick` 벡터)

적격 조건(모두): 자기 앱 아님(id가 `<앱슬러그>-`로 시작하거나 `tags`에 앱슬러그), `platforms`에 내 플랫폼(없으면 모두), `min_app_version` ≤ 앱 버전(점으로 나눈 숫자 비교), `starts_at ≤ 지금 < ends_at`, CTA가 위 해석으로 URL이 되고 그 URL이 **https + 허용 호스트와 정확히 일치**(대소문자 무시, 부분 일치·서브도메인 불가), 이 기기 노출 횟수 < `max_impressions_per_user`(없으면 3).
**CTA 해석(`resolve_cta`)**: `action: url`은 피드의 문구·주소 그대로. `action: store`는 `store`의 ID로 실행 중인 플랫폼의 스토어 주소를 만든다(iOS·macOS → `https://apps.apple.com/app/id<ios_app_id>`, Android → `https://play.google.com/store/apps/details?id=<android_package>`; `utm_source`=앱슬러그, `utm_campaign=feedcard`, `utm_content`=항목 id). ID는 검증한다(App Store ID는 숫자만, 패키지명은 `a.b` 형태의 문자·숫자·`_`만). Android 링크의 버튼 문구는 피드의 `cta.label`이 App Store를 가리키므로 **"Google Play"**(브랜드명, 번역하지 않음)로 바꿔 표시한다. 해석할 수 없는 CTA는 적격이 아니다.
고르는 법: 노출이 가장 적은 항목 → 같으면 `priority` 높은 것 → 같으면 목록에서 앞선 것. 카드가 처음 보일 때 그 항목 노출 +1.

**허용 호스트는 앱마다 설정이고 코드에 둔다**(피드가 바꿀 수 없게). 기준 목록은 `apps.apple.com`, `ovject.com`, `www.ovject.com`, `www.threads.com`, `threads.com`(벡터가 이 목록을 쓴다). Android 앱은 `play.google.com`을 더한다. 새 호스트를 쓰려면 앱을 업데이트해야 하므로 처음에 필요한 호스트를 넉넉히 넣는다.

## 6. 카드 UI (KAIRO 기준, 앱 디자인에 맞게 조정)

- 왼쪽 위 라벨 "OVJECT Apps"(**영어 고정**, 번역하지 않음, 11pt 세미볼드, 흰색 55%), 같은 줄 오른쪽 끝에 버튼 문구(피드 `cta.label`)와 ↗ 아이콘을 **같은 크기·색, 캡슐 없이**. 제목(17pt 세미볼드, 2줄)과 설명(14pt, 3줄)은 4pt 간격, 라벨 줄과는 10pt.
- 카드 전체가 하나의 버튼이고 탭하면 `cta.url`로 바로 이동한다. 접근성: 이름 "OVJECT Apps, <제목>", 힌트 `cta.label`, 링크 트레이트.
- 광고처럼 보이거나 클릭을 유도하는 문구는 쓰지 않는다. 스토어 로고는 쓰지 않는다(공식 배지는 Apple·Google 가이드를 따라야 한다).
- 갤러리처럼 상단 안전 영역까지 펼쳐지는 화면은 카드 위쪽 간격을 안전 영역에 맞춘다(KAIRO: 안전 영역 −12pt, 최소 16pt).

## 7. 어린이 대상 앱

Croco Roulette처럼 광고를 어린이 대상(`child-directed`)으로 요청하는 앱은 호스트의 `cta_hosts`를 **스토어 호스트만**(`apps.apple.com`, `play.google.com`) 두어 Threads·웹사이트 링크 항목(Oddside 등)이 들어오지 않게 한다. 앱 쪽 허용 목록도 같게 둔다. 스토어 외부로 나가는 링크를 Apple Kids 카테고리·Google Families 정책이 어떻게 다루는지(부모 확인 장치 등)는 앱별로 확인한다.

## 8. 검증

- 벡터: `python3 -I -m unittest discover -s tools -p "test_clients.py"` (참조 구현 + Swift 코어 + GDScript 코어). Swift 코어만: `cd clients/swift && swiftc OvjectHouseAdCore.swift main.swift -o /tmp/ov && /tmp/ov ../test-vectors.json`.
- 새 언어 포팅: `test-vectors.json`의 다섯 묶음(`locale`, `url_safety`, `semver`, `cta`, `pick`)을 읽어 같은 입력으로 호출하고 `expected`와 비교하는 단위 테스트를 만든다. `pick`은 케이스마다 `host_app`·`platform`·`app_version`·`now`·`impressions`·`items`(+ 있으면 `allowed_hosts`, 없으면 `reference_allowed_hosts`)를 입력으로 주고 `expected_id`(없으면 null)를 기대한다. `cta`는 `item`·`platform`·`host_app`을 주고 `expected`(`{label,url}` 또는 null)를 기대한다.
- 규칙을 바꿀 때는 `reference.py`와 벡터를 먼저 고치고, 모든 포팅(Swift 코어 복사본 포함)을 맞춘 뒤 테스트를 통과시킨다. KAIRO의 `Camera/Services/OvjectHouseAdCore.swift`와 `clients/swift/OvjectHouseAdCore.swift`는 항상 같은 내용이어야 한다(`cmp`로 확인). Croco의 `src/services/ovject_house_ad_core.gd`와 `clients/gdscript/ovject_house_ad_core.gd`도 마찬가지다.
