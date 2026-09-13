# 참고문헌 검증 보고서

**검증 시각**: 2026-09-12 20:49:41  
**검증 대상**: 10건

## 집계

- 총 항목: 10건
- ✅ 0건
- ⚠️ 0건
- ❌ 0건
- ⛔ 10건
- ➖ 0건

## 소스 및 판정 기준

- **DOI 실존 확인**: `https://doi.org/api/handles/{DOI}` (responseCode 1)
- **서지 대조**: Crossref `api.crossref.org/works/{DOI}` → 없으면 DataCite `api.datacite.org/dois/{DOI}`
- **arXiv 검증**: `export.arxiv.org/api/query?id_list=`
- **검색 기반**: Crossref `works?query.title=` 및 `works?query.bibliographic=`, 영문·비단행본이면 arXiv `search_query=ti:"제목"`
- **유사도**: `difflib.SequenceMatcher` ratio (소문자·구두점 제거), 접두어면 0.9 보정
- **판정 기준**: ✅ = 앵커 확인 + 유사도 ≥0.85 + 연도차 ≤1 + 저자 불일치 없음 / ⚠️ = 실존하나 차이 있음 / ❌ = 근거 없음 / ⛔ = 네트워크 오류 / ➖ = 비대상

## 항목별 결과

| # | 상태 | 입력 요약 | 근거 | 차이점 | 비고 |
|---|------|-----------|------|--------|------|
| 1 | ⛔ 확인불가 | 1. LeCun, Y., Bengio, Y., & Hinton, G. (2015). Deep learning. Nature, 521(7553),… | 오프라인 모드 — 외부 호출 차단됨 | — | 오프라인 모드로 생성됨 — 모든 항목이 확인불가 처리됨. |
| 2 | ⛔ 확인불가 | 2. Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N.,… | 오프라인 모드 — 외부 호출 차단됨 | — | 오프라인 모드로 생성됨 — 모든 항목이 확인불가 처리됨. |
| 3 | ⛔ 확인불가 | 3. Devlin, J., Chang, M.-W., Lee, K., & Toutanova, K. (2019). BERT: Pre-training… | 오프라인 모드 — 외부 호출 차단됨 | — | 오프라인 모드로 생성됨 — 모든 항목이 확인불가 처리됨. |
| 4 | ⛔ 확인불가 | 4. Kim, S., & Park, J. (2021). Quantum-enhanced federated learning for smart cit… | 오프라인 모드 — 외부 호출 차단됨 | — | 오프라인 모드로 생성됨 — 모든 항목이 확인불가 처리됨. |
| 5 | ⛔ 확인불가 | 5. Hochreiter, S., & Schmidhuber, J. (1999). Long short-term memory. Neural Comp… | 오프라인 모드 — 외부 호출 차단됨 | — | 오프라인 모드로 생성됨 — 모든 항목이 확인불가 처리됨. |
| 6 | ⛔ 확인불가 | 6. Lee, M. (2020). Edge-driven semantic labeling for IoT networks. https://doi.o… | 오프라인 모드 — 외부 호출 차단됨 | — | 오프라인 모드로 생성됨 — 모든 항목이 확인불가 처리됨. |
| 7 | ⛔ 확인불가 | 7. Goodfellow, I., Bengio, Y., & Courville, A. (2016). Deep learning. MIT Press. | 오프라인 모드 — 외부 호출 차단됨 | — | 오프라인 모드로 생성됨 — 모든 항목이 확인불가 처리됨. |
| 8 | ⛔ 확인불가 | 8. 김철수, 이영희 (2020). 딥러닝 기반 한국어 자연어 처리의 최근 동향. 한국어 정보처리학회지, 24(3), 45–62. | 오프라인 모드 — 외부 호출 차단됨 | — | 오프라인 모드로 생성됨 — 모든 항목이 확인불가 처리됨. |
| 9 | ⛔ 확인불가 | 9. Silver, D., Huang, A., Maddison, C. J., Guez, A., Sifre, L., van den Driessch… | 오프라인 모드 — 외부 호출 차단됨 | — | 오프라인 모드로 생성됨 — 모든 항목이 확인불가 처리됨. |
| 10 | ⛔ 확인불가 | 10. Python Software Foundation (2024). Python 3.12 documentation. Retrieved Sept… | 오프라인 모드 — 외부 호출 차단됨 | — | 오프라인 모드로 생성됨 — 모든 항목이 확인불가 처리됨. |

## 후속 조치

추가 확인이 필요한 항목이 없습니다.

## 한계

- 국문 학술지는 Crossref 미색인 가능성이 높아 영어 메타데이터만으로는 유사도가 낮게 나올 수 있음.
- 단행본·보고서는 색인이 불완전할 수 있음.
- 자동 검증은 참고용이며, 최종 판단은 사람이 수기로 해야 함.
- "❌ 미확인"을 "가짜"라고 단정하지 않음. 생성된 참고문헌일 가능성·인용 보류를 시사할 뿐임.
- DOI가 등록되었지만 서지 API에서 매칭되지 않는 경우 ⚠️로 표시하며, 오기재 가능성을 함께 알림.
