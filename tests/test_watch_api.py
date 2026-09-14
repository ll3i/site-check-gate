#!/usr/bin/env python3
"""
watch_api_test.py — /watch 엔드포인트 통합 테스트 (합성 mp4 + 사진)

실제 FastAPI 테스트 클라이언트로 POST /watch (video) → GET /jobs/{id} 폴링 → GET /jobs/{id}/annotated/{n} 확인.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

# 프로젝트 루트 먼저 설정
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from service.api.app import app

client = TestClient(app)


def test_watch_with_video():
    """합성 mp4로 /watch 테스트."""
    video_path = ROOT / "tests" / "fixtures" / "cache" / "demo_video_synthesized.mp4"
    assert video_path.is_file(), f"테스트 영상 없음: {video_path}"

    with open(video_path, "rb") as f:
        video_data = f.read()

    # POST /watch (video)
    response = client.post(
        "/watch",
        files={"video": ("demo_video.mp4", video_data, "video/mp4")},
    )
    assert response.status_code == 200, f"POST /watch 실패: {response.status_code} {response.text}"
    job = response.json()
    job_id = job["job_id"]
    print(f"POST /watch 성공: job_id={job_id}, status={job['status']}")

    # GET /jobs/{id} 폴링
    max_wait = 30
    for i in range(max_wait):
        resp = client.get(f"/jobs/{job_id}")
        data = resp.json()
        print(f"  폴링 {i+1}: status={data['status']}, step={data['step']}, progress={data['progress']}")
        if data["status"] == "done":
            break
        elif data["status"] == "error":
            print(f"  오류: {data.get('error')}")
            break
        time.sleep(1)
    else:
        print("  타임아웃")
        assert False, "타임아웃"

    # GET /watch/demo 도 확인
    resp = client.get("/watch/demo")
    assert resp.status_code == 200
    demo_data = resp.json()
    print(f"GET /watch/demo 성공: inspect_result.photos={len(demo_data['inspect_result']['photos'])}장")
    for p in demo_data["inspect_result"]["photos"]:
        print(f"  {p['photo']}: risk={p['risk_level']}, annotated={'O' if p.get('annotated') else 'X'}, detections={len(p['detections'])}")

    # GET /jobs/{id} 캐시에서 inspect_result 확인
    resp = client.get(f"/jobs/{job_id}")
    job_data = resp.json()
    print(f"\nGET /jobs/{job_id}: status={job_data['status']}")

    # annotated 서빙 테스트: 1번째 프레임
    resp = client.get(f"/jobs/{job_id}/annotated/1")
    if resp.status_code == 200:
        print(f"GET /jobs/{job_id}/annotated/1 성공: 콘텐츠 타입={resp.headers.get('content-type')}, 크기={len(resp.content)} bytes")
    else:
        print(f"GET /jobs/{job_id}/annotated/1 실패: {resp.status_code} {resp.text}")

    # 2번째 프레임
    resp = client.get(f"/jobs/{job_id}/annotated/2")
    if resp.status_code == 200:
        print(f"GET /jobs/{job_id}/annotated/2 성공: 콘텐츠 타입={resp.headers.get('content-type')}, 크기={len(resp.content)} bytes")
    else:
        print(f"GET /jobs/{job_id}/annotated/2 실패: {resp.status_code} {resp.text}")

    print("\n=== /watch 투어 완료 ===")


def test_watch_with_photos():
    """사진 3장으로 /watch 테스트."""
    demo_dir = ROOT / "assets" / "vision" / "demo_photos"
    photo_names = ["r1_l3_pipe.jpg", "r1_l2_loading.jpg", "r1_l1_electrical.jpg"]

    files = []
    for name in photo_names:
        p = demo_dir / name
        if p.is_file():
            files.append(("files", (name, open(p, "rb"), "image/jpeg")))

    if not files:
        print("데모 사진 없음, 스킵")
        return

    response = client.post("/watch", files=files)
    assert response.status_code == 200, f"POST /watch (photos) 실패: {response.status_code}"
    job = response.json()
    job_id = job["job_id"]
    print(f"POST /watch (photos) 성공: job_id={job_id}")

    # 폴링
    for i in range(15):
        resp = client.get(f"/jobs/{job_id}")
        data = resp.json()
        print(f"  폴링 {i+1}: status={data['status']}, step={data['step']}")
        if data["status"] == "done":
            break
        elif data["status"] == "error":
            print(f"  오류: {data.get('error')}")
            break
        time.sleep(1)

    # 결과 확인
    resp = client.get(f"/jobs/{job_id}")
    job_data = resp.json()
    if job_data["status"] == "done":
        result = job_data.get("result", {})
        inspect_result = result.get("inspect_result", {})
        photos = inspect_result.get("photos", [])
        print(f"사진 {len(photos)}장 분석 완료")
        for p in photos:
            print(f"  {p['photo']}: risk={p['risk_level']}, annotated={'O' if p.get('annotated') else 'X'}, detections={len(p['detections'])}")

    # annotated 서빙
    for n in range(1, len(photos) + 1):
        resp = client.get(f"/jobs/{job_id}/annotated/{n}")
        if resp.status_code == 200:
            print(f"GET /jobs/{job_id}/annotated/{n} 성공: {resp.headers.get('content-type')}, {len(resp.content)} bytes")
        else:
            print(f"GET /jobs/{job_id}/annotated/{n} 실패: {resp.status_code}")

    print("\n=== /watch (photos) 투어 완료 ===")


if __name__ == "__main__":
    print("=" * 60)
    print("1. /watch + 합성 mp4 테스트")
    print("=" * 60)
    test_watch_with_video()

    print("\n" + "=" * 60)
    print("2. /watch + 사진 테스트")
    print("=" * 60)
    test_watch_with_photos()

    print("\n✓ 모든 watch API 테스트 완료")
