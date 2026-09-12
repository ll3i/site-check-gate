# Changes — M1 예선 스킬 결함 수정 (2026-09-12)

## 개요
`prelim-skill/scripts/verify_refs.py` 의 5개 결함(F1~F5)을 수정하고,
`service/core/verify_refs.py` 에 반영함. 원본(`prelim-skill/`)은 수정하지 않음.

---

## F1: 미등록 DOI에서 status가 null로 새는 조기 return 경로

| 항목 | 내용 |
|---|---|
| **파일** | `service/core/verify_refs.py` |
| **함수** | `verify_item()` (케이스 1, DOI 미등록 분기) |
| **무엇을** | 469행 부근의 `return result` 문을 제거하고 `pass`로 변경. 하단 fallback 보정 로직(710행)이 `status=None`을 `unverified`로 보정하게 함. 또한 `check_doi_handle()`에서 `responseCode != 1`(예: 100 Not Found)도 미등록으로 처리. |
| **왜** | 기존에는 미등록 DOI + 제목 검색 유사도 < 0.72 일 때 여기서 조기 return 해서 보정 로직에 도달하지 못했고, status가 None인 채로 반환됨. 이로 인해 집계에서 해당 항목이 누락되고 Markdown 보고서에서 `?`로 렌더됨. 또한 핸들 API에서 responseCode 100(Not Found)도 등록으로 오인하는 문제가 있었음. |

---

## F2: 집계 합이 총 건수와 불일치

| 항목 | 내용 |
|---|---|
| **파일** | `service/core/verify_refs.py` |
| **함수** | `main()` (집계 출력부, 1035행 근처) |
| **무엇을** | 집계 출력 전 `sum(counts.values()) != len(results)` 불변식 검사 추가. 불일치 시 `⚠️ 오류: 집계 합(N) ≠ 총 건수(M). 데이터 무결성 위반!` 출력. 일치 시 "불변식 OK" 메시지 출력. 모든 console print를 `safe_print()`로 교체. |
| **왜** | 사용자가 보는 첫 숫자가 틀리면 나머지 결과를 신뢰할 수 없음. F1 수정으로 status=None 항목이 없어졌지만, 방어적 불변성 검사를 추가해 향후 회귀를 방지. |

---

## F3: --offline 무동작 → 실제 오프라인 모드

| 항목 | 내용 |
|---|---|
| **파일** | `service/core/verify_refs.py` |
| **함수** | `verify_item()` 및 `check_doi_handle()` |
| **무엇을** | (1) `verify_item()` 시작 부분에 오프라인 가드 추가: `if offline:` 이면 즉시 `status='unreachable'` 반환, 모든 외부 호출 차단. (2) `check_doi_handle()`에서 `responseCode != 1` (예: 100)일 때도 `False` 반환. (3) `cr_msg is None` 분기에도 오프라인 가드 삽입. (4) 중복 `return result` 제거 (672행). |
| **왜** | 기존에는 `--offline` 플래그가 arXiv 조회 실패(603행)에서만 참조되고, DOI 핸들 확인·Crossref·DataCite·제목 검색 경로에는 가드가 없어 문서와 동작이 불일치. 네트워크 차단 환경에서 긴 타임아웃 후 뒤섞인 결과가 나왔음. |

---

## F4: Windows cp949 콘솔에서 이모지 출력 크래시

| 항목 | 내용 |
|---|---|
| **파일** | `service/core/verify_refs.py` |
| **함수** | `_safe_encode_for_console()`, `safe_print()` (신규 함수), `main()` |
| **무엇을** | (1) `_safe_encode_for_console()`: 이모지→ASCII 폴백 매핑(✅→[OK], ⚠️→[WARN], ❌→[X], ⛔→[HOLD], ➖→[SKIP]). (2) `safe_print()`: 콘솔 출력 전 위 함수로 텍스트 변환. (3) `main()`의 모든 `print()` 호출을 `safe_print()`로 교체. |
| **왜** | Windows 콘솔(cp949)에서 `✅`(`\\u2705`) 등 출력 시 `UnicodeEncodeError` 발생. `PYTHONIOENCODING=utf-8` 우회 가능하나 심사자 환경에서 첫 실행이 예외로 종료됨. 파일 출력(UTF-8)은 영향 없음. |

### F4 보강 — 비-emoji 비-cp949 문자 처리 (2026-09-12 추가)

기존 `_safe_encode_for_console()`은 이모지 5종만 고정 매핑으로 치환하고, `—`(em dash, `\u2014`), `…`, `°`, `α` 등 매핑 목록에 없는 문자는 처리되지 않아 동일 방식의 `UnicodeEncodeError`가 재발했다. `--offline` 실행 시 **note**에 들어가는 `"오프라인 모드 — 외부 호출 차단됨"` 의 `—` 가 cp949에 없어 크래시가 발생한 것이 대표 사례.

보강 내용:
- 이모지 5종 ASCII 폴백 매핑은 가독성을 위해 유지.
- 그 외 문자는 현재 콘솔 인코딩(`sys.stdout.encoding`, 없으면 `utf-8`)으로 `encode(errors='replace')` → `decode()` 하여 문자 단위 대체(예: `—` → `?`)로 처리. 어떤 문자가 와도 크래시하지 않음.
- 인코딩 판별 실패 시 `ascii` 인코딩(errors='replace')로 최종 폴백.
- 파일 출력(UTF-8)에는 어떤 영향도 없음 (`safe_print`는 콘솔 출력에만 개입, 파일 쓰기는 기존 코드 그대로).

---

## F5: 실존 단행본을 ❌로 판정 → ⛔로 변경

| 항목 | 내용 |
|---|---|
| **파일** | `service/core/verify_refs.py` |
| **함수** | `verify_item()` (케이스 3, 검색 기반 판정 분기) |
| **무엇을** | `if not candidates:` 분기에서 `kind == 'book'` 이면 `status='unreachable'`(⛔) 로 설정하고 비고에 "단행본(kind=book) — Crossref 미색인으로 확인불가. ISBN/OpenLibrary 경로 필요." 명시. 그 외는 기존대로 `unverified`(❌). |
| **왜** | Crossref가 단행본을 잘 색인하지 않아 실존 단행본(Goodfellow et al. 2016, MIT Press)이 ❌ 미확인으로 판정됨. ❌(근거 없음)와 ⛔(확인 불가)는 다른 의미이며, 사용자에게 정직하게 "확인 불가"임을 알리는 것이 서비스 신뢰도에 중요. ISBN/OpenLibrary 경로는 M4에서 캐시 재생과 함께 구현 예정. |
