# Skill-to-Service 미니 PRD — 현장 보고 검증 게이트

**MABC 2026 결선 · Upstage Document Parse + 참고문헌 검증 + 법령·적법도급·사진 게이트 통합 FastAPI 서비스**

---

## ① 문제 정의

노랑봉투법(노동조합법 개정) 이후 시설관리 위탁운영 현장의 적법도급 점검은 수작업·경험 의존도가 높다. 점검 보고서 한 건을 확정하기까지 보고서에 적힌 법령 조문이 실제 존재하는지(환각 조항 리스크), 보고서 주장이 인용 문헌의 초록·본문과 일치하는지(가짜 문헌 / 진짜 문헌 + 틀린 주장), 첨부된 사진이 본문 서술을 실제로 뒷받침하는지, 원청-수급인 관계가 적법도급 기준을 충족하는지를 사람에 의존해 수 시간 동안 수동 교차 확인한다. 제출 직전에 "이거 진짜 조문 맞아?"라는 불안이 집중된다. 이 서비스는 그 불안을 파이프라인으로 대체한다: 잡는 것(실존하지 않는 조문·미확인 문헌·본문-초록 불일치·보고서 문장과 배치되는 사진)과 고치는 것(대체 문헌 제안·스냅샷 확보 후 재검증 유도)을 구분한다.

---

## ② 예선 스킬 → 서비스 스킬 매핑

| 예선 스킬(원본) | 서비스 내 역할 | 그대로 호출되는 부분 | 수정·확장(F1~F5 + E 계층) |
|---|---|---|---|
| **cite-check**(당선작, `prelim-skill/`) | **검증 엔진의 심장** — 실존 5단계 × 대조 3분기 | `service/core/verify_refs.py`(실존 판정 5단계), `service/core/match_claims.py`(주장-메타데이터 3분기 대조), `service/core/parse_refs.py`(참고문헌 파싱) | **F1**: 미등록 DOI status=null 누수 → 조기 return 제거 + DOI 핸들 responseCode 100 처리. **F2**: 집계 합 ≠ 총 건수 불일치 → 불변식 검사 추가. **F3**: `--offline` 무동작 → 전 경로 오프라인 가드. **F4**: Windows cp949 콘솔 이모지 크래시 → `safe_print()` + ASCII 폴백. **F5**: 실존 단행본을 ❌로 오판정 → ⛔(확인 불가)로 비대칭 강등. E 계층: 문헌 검증 로직을 법령·사진·적법도급으로 일반화(실존×대조 2차원 + 비대칭 강등). |
| pii-guard(`prelim-extra/`) | 텍스트 내 개인정보·비밀키 스캔 | `scripts/scan_pii.py`·`references/detection_catalog.md` 그대로 호출, 파이프라인 투입 전 텍스트 정제 단계에서 병용 | 수정 없음. |
| (신규) 법령 레지스트리 | 법령 인용 표지 추출 + 스냅샷 조회 | `service/core/verify_law_refs.py` — 본문에서 「산업안전보건법」 제38조 형태 표지 추출, `assets/law/*.json` 스냅샷 조회 | cite-check의 "실존 확인" 개념을 법령으로 일반화. LLM은 조문 본문을 만들지 않는다 — 스냅샷만 조회. |
| (신규) 적법도급 체크리스트 | 원청 직접성·혼재 작업·근태 통제 등 정황 분석 | `service/core/subcontract_check.py` — 고용노동부 파견 판단기준 5축·약 20항목 | cite-check의 "대조" 개념을 텍스트 정황 분석으로 확장. LLM은 판정 기준을 만들지 않는다 — 체크리스트 항목은 고정, 본문에서 근거 문장만 추출. |
| (신규) 사진 검사 | YOLO 객체 검출 + 보고서 문장-사진 대조 | `service/mcp_servers/photo_inspect_server.py`(detect_objects), `service/core/photo_detect.py`·`photo_match.py` | cite-check의 주장-근거 대조를 도메인 라우팅(defect·cleaning·gauge) 후 객체 검출로 확장. |

**핵심:** cite-check의 실존 5단계 + 대조 3분기가 서비스의 판정 심장으로 유지되고, 그 주변으로 법령·사진·적법도급이 "하지 않는 일(LLM이 조문·서지·라벨을 만들지 않는다)" 원칙을 지키며 일반화된다.

---

## ③ 아키텍처

**게이트 파이프라인 6섹션(`service/core/pipeline.py`):** ① Document Parse(Upstage API → PDF/DOCX → 요소 JSON, 동일 파일 cache/, 미설정 시 /jobs 400) → ② 절 분리(extract_refs.py, E10: 본문(body)과 참고문헌(ref) 요소 분리, 저자-연도·번호 마크 패턴으로 ref 분류) → ③ 참고문헌 검증(verify_refs.py, cite-check 심장: 실존 5단계 — ✅확인/DOI·Crossref·DataCite·arXiv 등록+제목 유사도 충족, ⚠️부분일치(제목 유사도 낮으나 후보 존재), ❌미확인(등록 안 됨+후보 없음), ⛔확인 불가(단행본 등 Crossref 미색인), ➖비대상) → ④ 인용 표지 추출(extract_claims.py: 본문에서 인용 표지와 주장 문장 추출) → ⑤ 연결 검사(link_check.py: 미인용 참조 + 목록 누락) → ⑥ 주장-근거 대조(match_claims.py) + 게이트 통합(주장-메타데이터 3분기: 뒷받침함 / 뒷받침 안 함 🔴오인용 / 판단 불가 → 문서 게이트: 제출 가능 / 보완 필요 / 확인 필요, M7d 확장으로 law_section·subcontract_section·photo_section·gate 키 추가).

**MCP 호스트 + 동봉 서버 11종(`mcpServers.json`):** cite_core(verify_references·match_claim, ★중심 축), pii_guard(scan_pii, 병용), law_registry(lookup_article·search_articles, assets/law/*.json 스냅샷 6종, 신규 일반화), site_rules(check_subcontract, 파견 판단기준 5축·약 20항목, 신규 일반화), scholar_search(search_papers, arXiv+Crossref 외부 API, 원본 예선), retraction_check(check_retraction, 외부 API, 원본 예선), url_check(check_url, 외부 HTTP, 원본 예선), wayback(find_snapshot, archive.org Wayback, 원본 예선), doc_parse(Document Parse API, UPSTAGE_API_KEY 필요, 신규 통합), photo_inspect(detect_objects, ultralytics+assets/vision/weights/*.pt 3종, 신규 일반화), contest_brief(없음, enabled:false placeholder).

**하지 않는 일:** ① LLM은 조문·서지·라벨을 만들지 않는다 — 법령 본문은 assets/law/*.json 스냅샷에서만 조회(실시간 law.go.kr 호출 없음), 서지 메타데이터는 Crossref·arXiv·DataCite·OpenAlex·Wayback 등 외부 출처에서 가져온 것만 사용, 사진 라벨은 YOLO 가중치(cleaning.pt·defect.pt·gauge.pt)가 붙인 검출 결과만 사용. ② 서비스 스스로 "이 문헌이 맞다"고 최종 판정하지 않는다 — 실존 5단계·대조 3분기·게이트 3상태는 모두 근거와 함께 제시하고 최종 제출 여부는 판정자가 결정. ③ 대체 문헌 제안은 "이런 후보가 있다"까지 — F5의 ISBN/OpenLibrary 경로, 국문 문헌 KCI/RISS/DBpia 수동 확인 권장 등 확인 불가 항목에 대해 다음으로 확인할 경로만 안내할 뿐 자동 대체하지 않는다.

---

## ④ 판정 체계

**실존 5단계(③ 검증):**

| 상태 | 아이콘 | 의미 | 예시 |
|---|---|---|---|
| 확인 | ✅ | DOI·Crossref·DataCite·arXiv 등록 + 제목 유사도 충족 | Smith et al. 2024 (arXiv:2401.12345) — 실재하면 |
| 부분일치 | ⚠️ | 등록 확인되나 제목 유사도 낮음, 후보 존재 | 유사 문헌 있으나 정확히 일치 안 함 |
| 미확인 | ❌ | DOI 미등록 + 검색 후보 없음/유사도 낮음 | 가짜 DOI, 없는 문헌 |
| 확인 불가 | ⛔ | Crossref 미색인(단행본) 등 확인 경로 부재 | Goodfellow et al. 2016 MIT Press — ISBN 필요 |
| 비대상 | ➖ | 검증 대상 아님 | 웹 자료, 개인 통신 등 |

**대조 3분기(⑥ 주장-근거):**

| 판정 | 아이콘 | 의미 |
|---|---|---|
| 뒷받침함 | ✅ | 문헌 초록·메타데이터가 본문 주장을 지지 |
| 뒷받침 안 함 | 🔴 | 실존 문헌에 대해 본문 주장이 초록·메타데이터와 불일치 → 오인용 |
| 판단 불가 | ⛔ | 문헌 메타데이터에 제목·초록이 비어 있음 등 대조 근거 부재 |

**문서 게이트(PRD §5, pipeline.py 게이트 종합):**

| 상태 | 조건 | 예시(데모 결과) |
|---|---|---|
| 제출 가능 | 미검증 0건, 오인용 0건, 사진 미매칭·⛔ 0건, 적법도급 위험 신호 없음, 법령 ❌ 0건 | — |
| 보완 필요 | 오인용 발생, 사진 '뒷받침 안 함', 적법도급 위험 신호, 미확인 존재, 법령 ❌ | 데모: 🔴 사진 대조 '뒷받침 안 함' 1건 |
| 확인 필요 | 판단 불가 3건 초과, 사진 미매칭·⛔ 과다, 법령 스냅샷 부재 | 데모: ⛔ 법령 스냅샷 미보유 4건(보완 필요 우선) |

우선순위: 보완 필요 > 확인 필요 > 제출 가능. 하나의 문서에서 여러 게이트 트리거가 동시 발생 가능하며 가장 높은 심각도가 최종 상태가 된다.

---

## ⑤ 실측 수치

- 총 git 커밋 14개 / 테스트 함수 정의 106건(test_host 5, test_mcp 5, test_extract 11, test_match 13, test_law 35, test_match_helpers 17, micro_bench_claims 20) / MCP 서버 11종(enabled 10 + contest_brief placeholder) / MCP 도구 합계 12개(cite_core 2, law_registry 2, 나머지 9개 × 1).
- E2E 게이트 판정 사례 1건(현장점검보고서_가온물류센터.pdf → 보완 필요, work/demo_pipeline_result.json gate.status) / 데모 파이프라인 소요 시간 18.68초(캐시 재사용 포함, 사진 2장 YOLO 검출·대조 포함, 동일 파일 elapsed_sec) / 데모 입력 PDF 1건 + 사진 2장(R1_L3_B동_옥외_배관.jpg, R1_L2_A동_1층_하역장.jpg, 동일 파일 photo_files).
- 사진 판정 결과: 총주장 3건, 매칭성공 2건, 매칭실패 1건, 뒷받침함 1 / 뒷받침 안 함 1(동일 파일 photo_section).
- 법령 표지 추출 4건, 스냅샷 미보유 4건(산업안전보건법 제38조·제99조 등, 동일 파일 law_section) / 적법도급 체크리스트 총 18항목, 위험 신호 1건(축1 항목1: "작업 지시·명령의 원청 직접성", 동일 파일 subcontract_section).
- YOLO 가중치 3종(cleaning.pt·defect.pt·gauge.pt, assets/vision/weights/) / 법령 스냅샷 6종(산업안전보건법·근로기준법·노동조합법·파견근로자보호법·중대재해처벌법·중대재해 처벌 등에 관한 법률, assets/law/*.json) / 캐시된 Document Parse 결과 tests/fixtures/cache/ 내 JSON 다수(arxiv_1706.03762 등).
- 외부 API 호출 비용: Upstage Document Parse API + Solar 호출(UPSTAGE_API_KEY 필요, 미설정 시 /jobs 400). 데모 파이프라인은 캐시 재생 경로(tests/fixtures/cache/ + work/demo_pipeline_result.json)로 키 없이도 결과 확인 가능.

---

## ⑥ 한계

- **스냅샷 미보유 시 ⛔:** 법령 스냅샷(assets/law/*.json)은 촬영 시점(확보일 2026-09-13) 기준이다. 스냅샷에 없는 법령 조문은 ⛔(확인 불가)로 판정된다. 실시간 law.go.kr 호출을 하지 않으므로 스냅샷 부재 시 대체 확인 경로가 없다.
- **초록 없는 문헌:** Crossref 등에 초록이 등록되지 않은 문헌은 대조 3분기에서 "판단 불가"로 떨어진다. 제목만으로 판정하지 않는다. 단행본은 Crossref 미색인으로 Goodfellow et al. 2016(MIT Press) 같은 실존 문헌도 ⛔로 오판정된다(ISBN/OpenLibrary 경로는 M4 이후 구현 예정).
- **판례 미반영:** 서비스는 현행 법령 스냅샷과 참고문헌 검증에 국한된다. 법원 판례·개정 법령·행정해석 변경은 반영되지 않는다. 한국어 DOI/KCI·RISS·DBpia 문헌은 Crossref 미등록 시 ❌/⛔로 떨어지며(KCI 연동은 별도 과제), 적법도급 체크리스트는 고정 항목이라 개별 사건의 특수성 판단은 사람의 최종 판단이 필요하다.

---

*문서 버전: M5 (2026-09-13) · 심사 배점: 문제정의 25 · 예선 스킬 활용도 30 · 사용성 15 · 독창성 20*
