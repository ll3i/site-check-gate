#!/usr/bin/env python3
"""
docparse_client.py — 파일을 Upstage Document Parse API로 보내고 응답 JSON을 반환하는 클라이언트.

API 사양 (PRD §4 실측 확인됨):
- POST https://api.upstage.ai/v1/document-digitization
- multipart 필드명: document
- model=document-parse, ocr=force, coordinates=true, output_formats=["text"]
- API 키: 환경변수 UPSTAGE_API_KEY
- 응답 JSON은 그대로 tests/fixtures/cache/에 저장 (재호출 회피)
"""

import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_URL = "https://api.upstage.ai/v1/document-digitization"
CACHE_DIR = Path("tests/fixtures/cache")


def _ensure_cache_dir() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def _cache_key(file_path: str) -> str:
    """파일 내용의 SHA256 앞 16자로 캐시 키 생성 (content-based, 안정적)."""
    raw = open(file_path, "rb").read()
    return hashlib.sha256(raw).hexdigest()[:16]


def _save_cache(key: str, data: dict) -> Path:
    cache_dir = _ensure_cache_dir()
    path = cache_dir / f"{key}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def _load_cache(key: str):
    """캐시된 응답이 있으면 반환, 없으면 None."""
    cache_dir = _ensure_cache_dir()
    path = cache_dir / f"{key}.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def _load_api_key() -> str:
    """UPSTAGE_API_KEY를 환경변수 → ~/.upstage/.env 순으로 로드.
    키는 코드·로그 어디에도 출력하지 않는다.
    """
    key = os.environ.get("UPSTAGE_API_KEY")
    if key:
        return key
    env_path = Path.home() / ".upstage" / ".env"
    if env_path.is_file():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("UPSTAGE_API_KEY="):
                    return line.split("=", 1)[1]
    return ""


def call_document_parse(file_path: str, timeout: int = 120) -> dict:
    """
    파일을 Document Parse API로 전송하고 응답 JSON dict를 반환한다.
    동일한 파일은 캐시에서 반환한다 (재호출 회피).
    """
    # 캐시 확인
    key = _cache_key(file_path)
    cached = _load_cache(key)
    if cached is not None:
        return cached

    api_key = _load_api_key()
    if not api_key:
        raise EnvironmentError(
            "UPSTAGE_API_KEY 환경변수와 ~/.upstage/.env 모두에서 "
            "API 키를 찾을 수 없습니다. Console에서 키를 발급받아 설정하세요."
        )

    # multipart/form-data 요청 구축
    boundary = "----WebKitFormBoundary" + hashlib.md5(str(os.urandom(16)).encode()).hexdigest()
    filename = os.path.basename(file_path)

    with open(file_path, "rb") as f:
        file_data = f.read()

    body_parts = []
    # document 필드
    body_parts.append(f"--{boundary}".encode())
    body_parts.append(
        f'Content-Disposition: form-data; name="document"; filename="{filename}"'.encode()
    )
    body_parts.append(b"Content-Type: application/octet-stream")
    body_parts.append(b"")
    body_parts.append(file_data)
    # model 필드
    body_parts.append(f"--{boundary}".encode())
    body_parts.append(b'Content-Disposition: form-data; name="model"')
    body_parts.append(b"")
    body_parts.append(b"document-parse")
    # ocr 필드
    body_parts.append(f"--{boundary}".encode())
    body_parts.append(b'Content-Disposition: form-data; name="ocr"')
    body_parts.append(b"")
    body_parts.append(b"force")
    # coordinates 필드
    body_parts.append(f"--{boundary}".encode())
    body_parts.append(b'Content-Disposition: form-data; name="coordinates"')
    body_parts.append(b"")
    body_parts.append(b"true")
    # output_formats 필드
    body_parts.append(f"--{boundary}".encode())
    body_parts.append(b'Content-Disposition: form-data; name="output_formats"')
    body_parts.append(b"")
    body_parts.append(b'["text"]')
    # 종료
    body_parts.append(f"--{boundary}--".encode())
    body_parts.append(b"")

    body = b"\r\n".join(body_parts)

    req = Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "mabc-cite-check/1.0",
        },
    )

    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Document Parse API HTTP {e.code}: {detail}") from e
    except URLError as e:
        raise RuntimeError(f"Document Parse API 연결 오류: {e.reason}") from e

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Document Parse 응답이 JSON이 아닙니다: {e}") from e

    # 캐시 저장
    _save_cache(key, data)

    return data


def call_document_parse_bytes(file_bytes: bytes, filename: str = "upload.pdf", 
                               timeout: int = 120) -> dict:
    """
    바이트 배열에서 Document Parse API 호출.
    캐시는 비활성화 (임시 파일 기반 호출용).
    """
    api_key = _load_api_key()
    if not api_key:
        raise EnvironmentError(
            "UPSTAGE_API_KEY 환경변수와 ~/.upstage/.env 모두에서 "
            "API 키를 찾을 수 없습니다. Console에서 키를 발급받아 설정하세요."
        )

    boundary = "----WebKitFormBoundary" + hashlib.md5(str(os.urandom(16)).encode()).hexdigest()

    body_parts = []
    body_parts.append(f"--{boundary}".encode())
    body_parts.append(
        f'Content-Disposition: form-data; name="document"; filename="{filename}"'.encode()
    )
    body_parts.append(b"Content-Type: application/octet-stream")
    body_parts.append(b"")
    body_parts.append(file_bytes)
    body_parts.append(f"--{boundary}".encode())
    body_parts.append(b'Content-Disposition: form-data; name="model"')
    body_parts.append(b"")
    body_parts.append(b"document-parse")
    body_parts.append(f"--{boundary}".encode())
    body_parts.append(b'Content-Disposition: form-data; name="ocr"')
    body_parts.append(b"")
    body_parts.append(b"force")
    body_parts.append(f"--{boundary}".encode())
    body_parts.append(b'Content-Disposition: form-data; name="coordinates"')
    body_parts.append(b"")
    body_parts.append(b"true")
    body_parts.append(f"--{boundary}".encode())
    body_parts.append(b'Content-Disposition: form-data; name="output_formats"')
    body_parts.append(b"")
    body_parts.append(b'["text"]')
    body_parts.append(f"--{boundary}--".encode())
    body_parts.append(b"")

    body = b"\r\n".join(body_parts)

    req = Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "mabc-cite-check/1.0",
        },
    )

    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Document Parse API HTTP {e.code}: {detail}") from e
    except URLError as e:
        raise RuntimeError(f"Document Parse API 연결 오류: {e.reason}") from e

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Document Parse 응답이 JSON이 아닙니다: {e}") from e


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("사용법: python docparse_client.py <파일경로>", file=sys.stderr)
        sys.exit(2)

    path = sys.argv[1]
    if not os.path.isfile(path):
        print(f"오류: 파일 없음 — {path}", file=sys.stderr)
        sys.exit(2)

    print(f"Document Parse 호출: {path}")
    result = call_document_parse(path)
    print(f"응답 keys: {list(result.keys())}")
    print(f"요소 수: {len(result.get('elements', result.get('content', [])))}")
    cache_key = _cache_key(path)
    print(f"캐시: tests/fixtures/cache/{cache_key}.json")
