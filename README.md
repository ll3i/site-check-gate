# 현장 보고 검증 게이트 (mabc-2026-final)

Upstage Document Parse + 참고문헌 검증 + 법령·적법도급·사진 게이트를 하나로 묶은 FastAPI 서비스.  
점검 보고서·계약 문서를 업로드하면 파싱→검증→게이트 판정을 통합 JSON 으로 반환한다.

---

## 아키텍처

### 게이트 파이프라인 (6 섹션)

`service/core/pipeline.py` 가 다음 6 단계를 순차 실행한다.

| 단계 | 모듈 | 역할 |
|------|------|------|
| ① | `docparse_client.py` | Upstage Document Parse API 로 PDF/DOCX → 요소(element) JSON. 동일 파일은 `tests/fixtures/cache/`에 캐시. |
| ② | `extract_refs.py` | 본문(body) 요소와 참고문헌(ref) 요소로 분리. |
| ③ | `verify_refs.py` | 참고문헌별 실존 5단계 판정 (DOI·Crossref·DataCite·arXiv·OpenAlex·archive.org·법률 스냅샷 기반). |
| ④ | `extract_claims.py` | 본문에서 인용 표지·주장 문장 추출. |
| ⑤ | `link_check.py` | 미인용 참조·목록 누락 검사. |
| ⑥ | `match_claims.py` + 게이트 통합 | 주장-메타데이터 3분기 대조 + 문서 게이트(PRD §5). **M7d 확장**: 법령(`verify_law_refs.py`), 적법도급(`subcontract_check.py`), 사진(`photo_detect.py`·`photo_match.py`)을 함께 판정해 `law_section`, `subcontract_section`, `photo_section`, `gate` 키를 결과에 추가. |

게이트 상태:

- **제출 가능** — 미검증 0건, 오인용 0건, 사진 미매칭·⛔ 0건, 적법도급 위험 신호 없음.
- **보완 필요** — 오인용 발생, 또는 사진 '뒷받침 안 함' 판정, 또는 적법도급 체크리스트 위험 신호.
- **확인 필요** — 판단 불가 3건 초과, 또는 사진 미매칭·⛔ 과다, 또는 법령 스냅샷 부재.

### MCP 서버 (11종)

`mcpServers.json` 에 등록된 서버. 각각 stdio MCP 로 독립 실행 가능하며, `service/api/app.py` 는 이들을 직접 사용하지 않고 `service/core/` 모듈을 직접 호출한다.

| 서버 | 도구 | 의존 |
|------|------|------|
| `cite_core` | `verify_references`, `match_claim` | `service/core/` 재활용, Solar 호출 필요(`UPSTAGE_API_KEY`) |
| `pii_guard` | 텍스트 내 개인정보·비밀키 스캔 | stdlib |
| `law_registry` | `lookup_article`, `search_articles` | `assets/law/*.json` 스냅샷 |
| `site_rules` | `check_subcontract` | 고용노동부 파견 판단기준 5축·약 20항목 |
| `scholar_search` | 논문 검색 (arXiv + Crossref) | 외부 API |
| `retraction_check` | 논문 철회 여부 | 외부 API |
| `url_check` | URL 상태 확인 | 외부 HTTP |
| `wayback` | archive.org Wayback Machine 스냅샷 검색 | 외부 API |
| `doc_parse` | Upstage Document Parse API 호출 | `UPSTAGE_API_KEY` |
| `photo_inspect` | YOLO 객체 검출 (`detect_objects`) | `ultralytics` + `assets/vision/weights/*.pt` |
| `contest_brief` | 대회 브리핑 요약 (비활성) | 다음 세션 구현 예정 |

---

## 60초 로컬 실행

Python 3.12 + pip 환경에서 의존성 설치 후 uvicorn 으로 올린다.

```bash
# 1. 의존성 설치 (비전 제외 — CPU 전용 ultralytics+torch 포함 시 아래 두 번째 명령)
pip install -r requirements.txt

#    비전 포함 설치 (PyTorch CPU 휠):
pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-vision.txt

# 2. 환경변수 설정
export UPSTAGE_API_KEY=<발급받은 키>
export PORT=8080

# 3. 실행
uvicorn service.api.app:app --host 0.0.0.0 --port $PORT
```

`http://localhost:8080/health` 로 서빙 확인, `http://localhost:8080/docs` 에서 Swagger UI 확인.

---

## Docker 실행

```bash
# 이미지 빌드 (로컬 Docker 필요)
docker build -t mabc-gate:latest .

# 컨테이너 실행
docker run --rm -p 8080:8080 \
  -e UPSTAGE_API_KEY=<발급받은 키> \
  -e PORT=8080 \
  mabc-gate:latest
```

빌드 시 포함되는 디렉터리: `service/`, `assets/`(law·vision 가중치 포함), `prelim-skill/`, `prelim-extra/`, `mcpServers.json`.

---

## Cloud Run 배포 (예시)

```bash
gcloud run deploy mabc-gate \
  --source . \
  --region asia-northeast3 \
  --port 8080 \
  --set-env-vars UPSTAGE_API_KEY=<발급받은 키> \
  --allow-unauthenticated
```

`--source .` 은 현재 디렉터리의 Dockerfile 을 자동 감지해 빌드·Deploy 한다.  
머신 유형은 기본값(String-256MiB)으로 시작하되, 비전 가중치를 로드하고 YOLO 추론 시 CPU 메모리가 증가하므로 실제 부하에서 `e2-medium` 이상으로 조정할 수 있다.

---

## 환경변수

| 변수 | 용도 | 필수 |
|------|------|------|
| `UPSTAGE_API_KEY` | Upstage Document Parse API·Solar 호출 인증. 미설정 시 `/jobs` 에서 400 오류 반환. | 예 (문서 파싱·Solar 사용 시) |
| `PORT` | uvicorn 리스닝 포트. 미설정 시 8080. | 아니오 |

---

## 원본 예선 스킬 위치

| 디렉터리 | 원본 | 설명 |
|----------|------|------|
| `prelim-skill/` | cite-check 원본 | 참고문헌 파싱·검증 규칙(`SKILL.md`, `references/verification_rules.md`, `scripts/parse_refs.py`, `scripts/verify_refs.py`). |
| `prelim-extra/pii-guard/` | pii-guard | 텍스트 개인정보·비밀키 스캔 (`scripts/scan_pii.py`, `references/detection_catalog.md`). |
| `prelim-extra/contest-brief/` | contest-brief | 대회 브리핑 요약 스킬 (`SKILL.md`, `scripts/analyze.py` 등). |

---

## 외부 API·출처 표기

서비스가 인용·검증에 사용하는 외부 출처.

| 출처 | 용도 | 비고 |
|------|------|------|
| doi.org | DOI 해석·정규화 | |
| Crossref | 논문 메타데이터 검색·著者·标题 검증 | `scholar_search` 서버 |
| DataCite | 데이터셋 DOI 메타데이터 | |
| arXiv | 프리프린트 메타데이터·존재 확인 | `scholar_search` 서버 |
| OpenAlex | 서지 메타데이터 (미지원 출처 보완) | |
| archive.org (Wayback Machine) | 웹 페이지 스냅샷 존재 확인 | `wayback` 서버 |
| law.go.kr | 법령 스냅샷 원본 (assets/law/*.json) | 서비스는 스냅샷만 조회, 실시간 호출 없음 |

위 출처 외 다른 외부 API는 사용하지 않는다.

---

## Ultralytics AGPL-3.0 고지

`assets/vision/weights/*.pt` (cleaning·defect·gauge) 추론과 `photo_inspect` 서버는 [Ultralytics](https://github.com/ultralytics/ultralytics) 패키지를 사용하며, 해당 패키지는 **AGPL-3.0** 라이선스로 배포된다.

이 이미지를 배포·제공할 때 Ultralytics AGPL-3.0 조건을 준수해야 하며, 적용 대상 서비스 전체를 AGPL-3.0 에 따라 소스공개해야 할 의무가 발생할 수 있다. 상업적·클로즈드 소스 배포를 계획한다면 별도 법률 검토를 권고한다.

---

## 파일 구성 (배포 이미지 포함)

```
service/            # FastAPI 앱·코어 파이프라인·MCP 서버
assets/
  law/              # 법령 스냅샷 JSON 6종
  vision/
    weights/        # YOLO 가중치 (cleaning.pt, defect.pt, gauge.pt)
    demo_photos/    # 데모 이미지
prelim-skill/       # cite-check 원본 스킬
prelim-extra/       # pii-guard·contest-brief
mcpServers.json     # MCP 서버 정의
requirements.txt    # 서비스 최소 의존성
requirements-vision.txt  # 비전 의존성 (ultralytics + torch CPU)
Dockerfile
.dockerignore
```
