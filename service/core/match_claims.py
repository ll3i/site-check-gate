#!/usr/bin/env python3
"""
match_claims.py — solar-pro4(chat API, temperature=0)로 주장-근거 대조.

계약:
- 출력: JSON {"verdict","quote","reason"} -- verdict 3분기 고정.
- 메타데이터(제목·초록) 밖 지식 사용 금지 → 프롬프트에 명시.
- 코드 후처리(프롬프트 아님): PRD §6 3번 비대칭 강등.
- quote 실재 검사(문자열 대조기): ...·… 로 분할 → 15자 미만 구절 제외 →
  소문자화·공백 접기·따옴표 통일·양끝 구두점 제거 후 substring.
- 동시 4 병렬, 항목별 결과 캐시(tests/fixtures/cache/).
"""

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── 상수 ──────────────────────────────────────────────────────────────────────

API_URL = "https://api.upstage.ai/v1/chat/completions"
CACHE_DIR = Path("tests/fixtures/cache")
MAX_PARALLEL = 4

# 판정 3분기
VERDICT_SUPPORTED = "뒷받침함"
VERDICT_NOT_SUPPORTED = "뒷받침 안 함"
VERDICT_CANNOT_JUDGE = "판단 불가"

# 태그
TAG_NO_QUOTE_REJECTION = "무인용 거절"


# ── 캐시 ──────────────────────────────────────────────────────────────────────

def _cache_key(claim: str, metadata_title: str, metadata_abstract: str) -> str:
    """항목별 캐시 키 (내용 기반). 시스템 프롬프트 해시를 포함하여 프롬프트 변경 시
    구버전 캐시가 반환되는 결함을 방지한다."""
    prompt_hash = hashlib.sha256(SYSTEM_PROMPT.encode('utf-8')).hexdigest()[:16]
    raw = f"{prompt_hash}\n{claim}\n{metadata_title}\n{metadata_abstract}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]


def _load_cache(key: str) -> Optional[Dict[str, Any]]:
    cache_dir = _ensure_cache_dir()
    path = cache_dir / f"match_{key}.json"
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def _save_cache(key: str, data: Dict[str, Any]) -> Path:
    cache_dir = _ensure_cache_dir()
    path = cache_dir / f"match_{key}.json"
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def _ensure_cache_dir() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


# ── 문자열 대조기 (PRD §6 4번) ────────────────────────────────────────────────

def normalize_text(s: str) -> str:
    """
    문자열 대조용 정규화:
    - 소문자화
    - 따옴표 통일 (쌍따옴표·따옴표 모두 단일 아포스트로피로)
    - 한국어 괄호(「」「『』) 및 생략부호(…) → 공백으로 치환
    - 공백 접기 (연속 공백 → 단일 공백, 앞뒤 공백 제거)
    - 모든 비단어 문자(구두점 등)를 공백으로 치환
    """
    s = s.lower()
    # 따옴표 통일: 여러 종류 모두 단일 아포스트로피로
    s = s.replace('\u201c', "'").replace('\u201d', "'")
    s = s.replace('\u2018', "'").replace('\u2019', "'")
    s = s.replace('"', "'").replace('"', "'")
    s = s.replace('"', "'").replace('"', "'")
    # 한국어 괄호 및 생략부호 → 공백으로 치환
    s = s.replace('\u300c', ' ').replace('\u300d', ' ')  # 「」
    s = s.replace('\u300e', ' ').replace('\u300f', ' ')  # 『』
    s = s.replace('\u2026', ' ')  # …
    # 공백 접기
    s = re.sub(r'\s+', ' ', s).strip()
    # 모든 비단어 문자(구두점 등)를 공백으로 치환 (\w = [a-zA-Z0-9_], 한글 포함)
    # 단, 아포스트로피는 이미 치환했으므로 여기서 제거되어도 무방
    s = re.sub(r'[^\w\s]', ' ', s)
    # 공백 재접기 (비단어 문자 → 공백 치환으로 생긴 연속 공백 정리)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def split_ellipsis(text: str) -> List[str]:
    """
    ... 또는 … 기준으로 분할.
    연속된 ...을 하나의 구분자로 처리.
    """
    # … 또는 ...을 구분자로 분할
    parts = re.split(r'\.\.\.|…', text)
    return [p.strip() for p in parts if p.strip()]


def quote_exists_in_metadata(
    quote: str,
    metadata_title: str,
    metadata_abstract: str,
    fallback_ngram: bool = True,
) -> bool:
    """
    quote 실재 검사 (문자열 대조기, PRD §6 4번).

    사양(순서 엄수):
    ① 정규화 함수 적용 = 소문자화, 공백 접기, 굽은따옴표를 곧은따옴표로 통일,
       양끝의 따옴표·구두점 strip
    ② quote를 '...' 또는 '…' 로 분할
    ③ 각 구절을 정규화하고 15자 미만 구절은 버림
    ④ 남은 구절이 0개면 False 반환
    ⑤ 남은 모든 구절이 정규화된 메타데이터 문자열의 substring 이면 True,
       하나라도 아니면 False.
       부분 토큰 매칭·유사도·느슨한 비교 금지 — 정확한 substring 만.
    """
    if not quote:
        return False

    # ── ① 정규화 함수 ────────────────────────────────────────────────────────
    def _normalize(s: str) -> str:
        # 소문자화
        s = s.lower()
        # 굽은따옴표 → 곧은따옴표 통일
        s = s.replace('\u2018', "'").replace('\u2019', "'")  # ' '
        s = s.replace('\u201c', "'").replace('\u201d', "'")  # " "
        # 공백 접기 (연속 공백 → 단일 공백)
        s = re.sub(r'\s+', ' ', s)
        # 양끝 따옴표·구두점 strip (… 포함, 공백도 제거)
        strip_chars = "'\" \u2026" + '!"#$%&()*+,-./:;<=>?@[\\]^_`{|}~'
        s = s.strip(strip_chars)
        return s

    # ── 메타데이터 정규화 ─────────────────────────────────────────────────────
    metadata = f"{metadata_title} {metadata_abstract}"
    norm_metadata = _normalize(metadata)

    # ── ② quote를 '...' 또는 '…' 로 분할 ────────────────────────────────────
    raw_parts = re.split(r'\.\.\.|…', quote)

    # ── ③ 각 구절을 정규화하고 15자 미만 구절은 버림 ────────────────────────
    kept: List[str] = []
    for raw in raw_parts:
        p = _normalize(raw)
        if len(p) >= 15:
            kept.append(p)

    # ── ④ 남은 구절이 0개면 False 반환 ───────────────────────────────────────
    if not kept:
        return False

    # ── ⑤ 남은 모든 구절이 정규화된 메타데이터의 substring 인지 확인 ────────
    for fragment in kept:
        if fragment not in norm_metadata:
            return False

    return True


# ── solar-pro4 API 호출 ───────────────────────────────────────────────────────

def _get_api_key() -> str:
    key = os.environ.get("UPSTAGE_API_KEY")
    if key:
        return key
    env_path = Path.home() / ".upstage" / ".env"
    if env_path.is_file():
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith("UPSTAGE_API_KEY="):
                    return line.split("=", 1)[1]
    return ""


def call_solar_pro4(
    messages: List[Dict[str, str]],
    temperature: float = 0.0,
    timeout: int = 60,
) -> Optional[str]:
    """
    solar-pro4 chat API 호출.
    반환: 응답 content 문자열, 실패 시 None.
    """
    api_key = _get_api_key()
    if not api_key:
        print("오류: UPSTAGE_API_KEY 없음", file=sys.stderr)
        return None

    payload = {
        "model": "solar-pro4",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 2048,
        "top_p": 1.0,
    }

    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')

    req = urllib.request.Request(
        API_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "mabc-cite-check/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            result = json.loads(raw)
            choices = result.get('choices', [])
            if choices:
                return choices[0].get('message', {}).get('content', '')
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        print(f"HTTP {e.code}: {body[:200]}", file=sys.stderr)
    except urllib.error.URLError as e:
        print(f"연결 오류: {e.reason}", file=sys.stderr)
    except Exception as e:
        print(f"오류: {e}", file=sys.stderr)

    return None


# ── 시스템 프롬프트 ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """당신은 학술 문헌 인용 검증 도구입니다.

## 작업
주어진 주장 문장(claim)이 제공된 문헌 메타데이터(제목, 초록) 안에서 실제로 뒷받침되는지 판단하세요.

## 중요 규칙
1. 제공된 메타데이터(제목과 초록)만 사용하세요. 메타데이터 밖의 지식이나 기억에 의존하지 마세요.
2. 메타데이터에 없는 내용은 "판단 불가"로 판정하세요.
3. 출력은 반드시 다음 형식의 JSON 하나만 출력하세요:
   {"verdict": "뒷받침함" | "뒷받침 안 함" | "판단 불가", "quote": "원문 구절 (비어있을 수 있음)", "reason": "판단 근거 (한국어)"}
4. "quote"는 메타데이터에서 실제 존재하는 구절을 인용하세요. ... 또는 …로 여러 구절을 이어붙일 수 있습니다.
5. "뒷받침함"은 메타데이터의 구절이 주장의 의미를 실제로 지지할 때만 사용하세요.
6. "뒷받침 안 함"은 메타데이터에 주장을 지지하는 근거가 없을 때 사용하세요.
7. "판단 불가"는 메타데이터만으로는 판단이 불가능할 때 사용하세요 (예: 초록이 없거나 주장과 무관).

## 제한
- metadata에 없는 수치·도메인 정보를 지어내지 마세요.
- 논문은 메타데이터(제목+초록)로만 판단하세요. 전문(full text) 내용은 알지 못합니다.
"""


# ── 단일 대조 ─────────────────────────────────────────────────────────────────

def match_single_claim(
    claim: str,
    metadata_title: str,
    metadata_abstract: str,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """
    단일 주장에 대해 solar-pro4로 주장-근거 대조.

    반환:
    {
        'claim': 주장 텍스트,
        'verdict': "뒷받침함" | "뒷받침 안 함" | "판단 불가",
        'quote': 원문 구절 (또는 ''),
        'reason': 판단 근거,
        'metadata_title': 메타데이터 제목,
        'metadata_abstract': 메타데이터 초록,
        'quote_exists': quote 실재 검사 결과 (bool),
        'post_processed': 코드 후처리 적용 여부 (bool),
        'tags': [태그 리스트],
    }
    """
    # 캐시 확인
    if use_cache:
        key = _cache_key(claim, metadata_title, metadata_abstract)
        cached = _load_cache(key)
        if cached:
            return cached

    # 메타데이터 구성
    metadata = f"제목: {metadata_title}\n\n초록: {metadata_abstract}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"## 주장 문장\n\n{claim}\n\n"
            f"## 문헌 메타데이터\n\n{metadata}\n\n"
            f"## 출력\n\n"
            f"위 주장이 문헌 메타데이터에 의해 뒷받침되는지 판단하고, "
            f"JSON 하나만 출력하세요."
        )},
    ]

    response = call_solar_pro4(messages, temperature=0.0)

    result: Dict[str, Any] = {
        'claim': claim,
        'verdict': VERDICT_CANNOT_JUDGE,
        'quote': '',
        'reason': '',
        'metadata_title': metadata_title,
        'metadata_abstract': metadata_abstract,
        'quote_exists': False,
        'post_processed': False,
        'tags': [],
        'raw_response': response or '',
    }

    # 응답 파싱
    if response:
        # JSON 추출 (여러 줄 중 첫 JSON 객체)
        json_match = re.search(r'\{[^}]*"verdict"[^}]*\}', response)
        if json_match:
            try:
                parsed = json.loads(json_match.group(0))
                result['verdict'] = parsed.get('verdict', VERDICT_CANNOT_JUDGE)
                result['quote'] = parsed.get('quote', '')
                result['reason'] = parsed.get('reason', '')
            except json.JSONDecodeError:
                pass
        else:
            # JSON이 아닌 경우 keywords로 추정
            if '뒷받침함' in response:
                result['verdict'] = VERDICT_SUPPORTED
            elif '뒷받침 안 함' in response:
                result['verdict'] = VERDICT_NOT_SUPPORTED
            elif '판단 불가' in response:
                result['verdict'] = VERDICT_CANNOT_JUDGE

    # ── 코드 후처리: 비대칭 강등 (PRD §6 3번) ────────────────────────────

    original_verdict = result['verdict']

    # quote 실재 검사
    result['quote_exists'] = quote_exists_in_metadata(
        result['quote'],
        result['metadata_title'],
        result['metadata_abstract'],
    )

    if original_verdict == VERDICT_SUPPORTED:
        # 뒷받침함 → quote가 비었거나 실재하지 않으면 판단 불가로 강등
        if not result['quote'] or not result['quote_exists']:
            result['verdict'] = VERDICT_CANNOT_JUDGE
            result['post_processed'] = True
            result['reason'] = (
                f"[강등] 원문 quote 부재/미실재로 '{VERDICT_CANNOT_JUDGE}'로 강등. "
                f"원본 판정: {original_verdict}"
            )

    elif original_verdict == VERDICT_NOT_SUPPORTED:
        # 뒷받침 안 함 → quote가 비면 유지하되 "무인용 거절" 태그
        if not result['quote']:
            result['tags'].append(TAG_NO_QUOTE_REJECTION)
            result['post_processed'] = True
            if result['reason']:
                result['reason'] = f"[무인용 거절] {result['reason']}"
            else:
                result['reason'] = (
                    "[무인용 거절] 근거 구절 없이 거절됨 — 확인 필요 큐로 이동"
                )

    # 캐시 저장
    if use_cache:
        key = _cache_key(claim, metadata_title, metadata_abstract)
        _save_cache(key, result)

    return result


# ── 배치 처리 (4 병렬) ───────────────────────────────────────────────────────

def match_claims_batch(
    items: List[Dict[str, Any]],
    use_cache: bool = True,
    max_parallel: int = MAX_PARALLEL,
) -> List[Dict[str, Any]]:
    """
    여러 주장-메타데이터 쌍에 대해 병렬 대조.

    items: [
        {'claim': ..., 'metadata_title': ..., 'metadata_abstract': ..., 'ref_id': ...},
        ...
    ]

    반환: 각 항목별 결과 리스트 (입력 순서 유지).
    """
    if not items:
        return []

    results_map: Dict[int, Dict[str, Any]] = {}

    def process_one(idx_item: Tuple[int, Dict[str, Any]]) -> Tuple[int, Dict[str, Any]]:
        idx, item = idx_item
        result = match_single_claim(
            claim=item['claim'],
            metadata_title=item.get('metadata_title', ''),
            metadata_abstract=item.get('metadata_abstract', ''),
            use_cache=use_cache,
        )
        if 'ref_id' in item:
            result['ref_id'] = item['ref_id']
        return idx, result

    with ThreadPoolExecutor(max_workers=max_parallel) as executor:
        futures = {
            executor.submit(process_one, (i, item)): i
            for i, item in enumerate(items)
        }
        for future in as_completed(futures):
            idx, result = future.result()
            results_map[idx] = result

    return [results_map[i] for i in range(len(items))]


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='주장-근거 대조 (solar-pro4)')
    parser.add_argument('input_json', help='입력 JSON 경로 (claim-meta 쌍 리스트)')
    parser.add_argument('--output', '-o', default='work/match_results.json',
                        help='출력 JSON 경로')
    parser.add_argument('--parallel', type=int, default=MAX_PARALLEL,
                        help='병렬 수')
    parser.add_argument('--no-cache', action='store_true',
                        help='캐시 사용 안 함')
    args = parser.parse_args()

    with open(args.input_json, 'r', encoding='utf-8') as f:
        items = json.load(f)

    print(f"주장 {len(items)}건 대조 시작 (병렬 {args.parallel}, 캐시={'OFF' if args.no_cache else 'ON'})")

    t0 = time.time()
    results = match_claims_batch(
        items,
        use_cache=not args.no_cache,
        max_parallel=args.parallel,
    )
    elapsed = time.time() - t0

    # 집계
    counts = {
        VERDICT_SUPPORTED: 0,
        VERDICT_NOT_SUPPORTED: 0,
        VERDICT_CANNOT_JUDGE: 0,
    }
    for r in results:
        v = r.get('verdict', VERDICT_CANNOT_JUDGE)
        if v in counts:
            counts[v] += 1

    print(f"완료: {elapsed:.2f}초")
    print(f"  뒷받침함: {counts[VERDICT_SUPPORTED]}")
    print(f"  뒷받침 안 함: {counts[VERDICT_NOT_SUPPORTED]}")
    print(f"  판단 불가: {counts[VERDICT_CANNOT_JUDGE]}")

    # 출력 저장
    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump({
            'meta': {
                'input': args.input_json,
                'elapsed_sec': elapsed,
                'parallel': args.parallel,
                'use_cache': not args.no_cache,
            },
            'results': results,
        }, f, ensure_ascii=False, indent=2)
    print(f"결과 저장: {args.output}")
