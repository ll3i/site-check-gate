# 참고문헌 검증 보고서

**검증 시각**: 2026-09-12 20:20:15  
**검증 대상**: 10건

## 집계

- 총 항목: 10건
- ✅ 4건
- ⚠️ 0건
- ❌ 5건
- ⛔ 0건
- ➖ 1건

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
| 1 | ✅ 확인 | 1. LeCun, Y., Bengio, Y., & Hinton, G. (2015). Deep learning. Nature, 521(7553),… | DOI 핸들 확인: 등록됨(responseCode 1); Crossref 제목 유사도: 0.90; 교차 저자: 입력 'None' vs 소스 'LeCun'; 연도 차이: 입력 2015 vs 소스 2015 (차 0) | — | 확인 완료: DOI 실존 + 제목 유사도 0.90 + 연도차 0년 |
| 2 | ✅ 확인 | 2. Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N.,… | arXiv 1706.03762 실존 확인; arXiv 제목 유사도: 0.90 | — | ✅ 확인: arXiv 1706.03762 실존, 제목 유사도 0.90 |
| 3 | ✅ 확인 | 3. Devlin, J., Chang, M.-W., Lee, K., & Toutanova, K. (2019). BERT: Pre-training… | crossref 제목 유사도: 0.90 | — | ✅ 확인(검색 기반): 제목 유사도 0.90, 출처 crossref. |
| 4 | ❌ 미확인 | 4. Kim, S., & Park, J. (2021). Quantum-enhanced federated learning for smart cit… | crossref 제목 유사도: 0.59 | — | 검색 결과 있으나 유사도 0.59 낮음. |
| 5 | ❌ 미확인 | 5. Hochreiter, S., & Schmidhuber, J. (1999). Long short-term memory. Neural Comp… | DOI 핸들 확인: 미등록 | — | DOI 미등록, 검색 후보 있으나 제목 유사도 낮음. DOI 10.1162/neco.1999.9.8.1735 미등록 — 가짜 단정 아님, 생성된 참고문헌 가능성 |
| 6 | ❌ 미확인 | 6. Lee, M. (2020). Edge-driven semantic labeling for IoT networks. https://doi.o… | DOI 핸들 확인: 미등록 | — | DOI 미등록, 검색 후보 있으나 제목 유사도 낮음. DOI 10.1234/edsl.2020.0412 미등록 — 가짜 단정 아님, 생성된 참고문헌 가능성 |
| 7 | ❌ 미확인 | 7. Goodfellow, I., Bengio, Y., & Courville, A. (2016). Deep learning. MIT Press. | crossref 제목 유사도: 0.51 | — | 검색 결과 있으나 유사도 0.51 낮음. |
| 8 | ❌ 미확인 | 8. 김철수, 이영희 (2020). 딥러닝 기반 한국어 자연어 처리의 최근 동향. 한국어 정보처리학회지, 24(3), 45–62. | crossref 제목 유사도: 0.43 | — | 검색 결과 있으나 유사도 0.43 낮음. |
| 9 | ✅ 확인 | 9. Silver, D., Huang, A., Maddison, C. J., Guez, A., Sifre, L., van den Driessch… | crossref 제목 유사도: 0.90 | — | ✅ 확인(검색 기반): 제목 유사도 0.90, 출처 crossref. |
| 10 | ➖ 비대상 | 10. Python Software Foundation (2024). Python 3.12 documentation. Retrieved Sept… | kind=web, DOI/arXiv 없음 — 비대상(➖) | — | 웹 문헌(kind=web)은 DOI/arXiv 대상 아님. URL 기반 별도 확인 권장. |

## 교정 서지 (소스 메타데이터 그대로)

**[1]** DOI: 10.1038/nature14539 | 저자: LeCun, Yann, Bengio, Yoshua, Hinton, Geoffrey | 제목: Deep learning | 연도: 2015 | 출처: Nature | URL: https://doi.org/10.1038/nature14539
  _입력_: 1. LeCun, Y., Bengio, Y., & Hinton, G. (2015). Deep learning. Nature, 521(7553), 436–444. https://doi.org/10.1038/nature14539

**[2]** arXiv: 1706.03762 | 저자: Ashish Vaswani | 제목: Attention Is All You Need | 연도: 2017 | URL: https://arxiv.org/pdf/1706.03762v7
  _입력_: 2. Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., Kaiser, Ł., & Polosukhin, I. (2017). Attention is all you need. arXiv:1706.03762.

**[3]** DOI: 10.18653/v1/n19-1423 | 저자: Devlin, Jacob, Chang, Ming-Wei, Lee, Kenton, Toutanova, Kristina | 제목: BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding | 연도: 2019 | 출처: Proceedings of the 2019 Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies, Volume 1 (Long and Short Papers) | URL: https://doi.org/10.18653/v1/n19-1423
  _입력_: 3. Devlin, J., Chang, M.-W., Lee, K., & Toutanova, K. (2019). BERT: Pre-training of deep bidirectional transformers for language understanding. In Proceedings of NAACL-HLT 2019.

**[9]** DOI: 10.1038/nature16961 | 저자: Silver, David, Huang, Aja, Maddison, Chris J., Guez, Arthur, Sifre, Laurent, van den Driessche, George, Schrittwieser, Julian, Antonoglou, Ioannis, Panneershelvam, Veda, Lanctot, Marc, Dieleman, Sander, Grewe, Dominik, Nham, John, Kalchbrenner, Nal, Sutskever, Ilya, Lillicrap, Timothy, Leach, Madeleine, Kavukcuoglu, Koray, Graepel, Thore, Hassabis, Demis | 제목: Mastering the game of Go with deep neural networks and tree search | 연도: 2016 | 출처: Nature | URL: https://doi.org/10.1038/nature16961
  _입력_: 9. Silver, D., Huang, A., Maddison, C. J., Guez, A., Sifre, L., van den Driessche, G., Schrittwieser, J., Antonoglou, I., Panneershelvam, V., Lanctot, M., Dieleman, S., Grewe, D., Nham, J., Kalchbrenn


## 후속 조치

다음 항목은 추가 확인이 필요합니다:

- **[4]** ❌ 미확인: 검색 결과 있으나 유사도 0.59 낮음.
- **[5]** ❌ 미확인: DOI 미등록, 검색 후보 있으나 제목 유사도 낮음. DOI 10.1162/neco.1999.9.8.1735 미등록 — 가짜 단정 아님, 생성된 참고문헌 가능성
- **[6]** ❌ 미확인: DOI 미등록, 검색 후보 있으나 제목 유사도 낮음. DOI 10.1234/edsl.2020.0412 미등록 — 가짜 단정 아님, 생성된 참고문헌 가능성
- **[7]** ❌ 미확인: 검색 결과 있으나 유사도 0.51 낮음.
- **[8]** ❌ 미확인: 검색 결과 있으나 유사도 0.43 낮음.

## 한계

- 국문 학술지는 Crossref 미색인 가능성이 높아 영어 메타데이터만으로는 유사도가 낮게 나올 수 있음.
- 단행본·보고서는 색인이 불완전할 수 있음.
- 자동 검증은 참고용이며, 최종 판단은 사람이 수기로 해야 함.
- "❌ 미확인"을 "가짜"라고 단정하지 않음. 생성된 참고문헌일 가능성·인용 보류를 시사할 뿐임.
- DOI가 등록되었지만 서지 API에서 매칭되지 않는 경우 ⚠️로 표시하며, 오기재 가능성을 함께 알림.
