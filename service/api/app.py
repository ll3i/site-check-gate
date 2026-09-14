import json
import mimetypes
import os
import uuid
import tempfile
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from service.core.pipeline import run_pipeline
from service.core.inspect_mode import inspect_photos
from service.core.draft_report import generate_draft
from service.core.video_frames import extract_frames
from service.core.annotate import annotate_image_with_risk_badge

app = FastAPI(title="현장 보고 검증 게이트")

# ── 메모리 Job 저장고 ────────────────────────────────────────────────────────
jobs: dict[str, dict] = {}

STATIC_DIR = Path(__file__).resolve().parent.parent / "web"
ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"


# ── 경로 안전화 헬퍼 ─────────────────────────────────────────────────────────
def _safe_save_path(tmpdir: str, original_filename: str) -> str:
    """원본 파일명을 보존하되 경로 안전화만 수행하여 저장 경로를 반환한다."""
    name = original_filename.replace("\x00", "")
    name = name.replace("/", "_").replace("\\", "_")
    name = name.replace("..", "")
    if not name.strip():
        name = "unnamed"
    base_path = os.path.join(tmpdir, name)
    if not os.path.exists(base_path):
        return base_path
    base, ext = os.path.splitext(name)
    counter = 1
    while True:
        new_name = f"{base}_{counter}{ext}"
        new_path = os.path.join(tmpdir, new_name)
        if not os.path.exists(new_path):
            return new_path
        counter += 1


def _build_demo_job(tmpdir: str) -> tuple[str, list[str]]:
    """데모 문서와 사진 2장을 tmpdir에 복사하고 경로를 반환한다."""
    # 문서
    demo_doc_src = ASSETS_DIR / "demo" / "demo_report_gaon.pdf"
    if not demo_doc_src.is_file():
        raise FileNotFoundError(f"데모 문서 없음: {demo_doc_src}")
    doc_path = os.path.join(tmpdir, "demo_report.pdf")
    with open(doc_path, "wb") as f:
        f.write(demo_doc_src.read_bytes())

    # 사진 2장
    photo_dir = ASSETS_DIR / "vision" / "demo_photos"
    photo_names = ["r1_l3_pipe.jpg", "r1_l2_loading.jpg"]
    photo_paths: list[str] = []
    for pn in photo_names:
        src = photo_dir / pn
        if not src.is_file():
            raise FileNotFoundError(f"데모 사진 없음: {src}")
        dst = os.path.join(tmpdir, pn)
        with open(dst, "wb") as f:
            f.write(src.read_bytes())
        photo_paths.append(dst)

    return doc_path, photo_paths


# ── health ───────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "service": "현장 보고 검증 게이트"}


# ── POST /jobs ───────────────────────────────────────────────────────────────
@app.post("/jobs")
async def create_job(
    background_tasks: BackgroundTasks,
    document: UploadFile = File(..., description="점검 보고서·계약 문서 (PDF/DOCX 등)"),
    photos: List[UploadFile] = File(default=[], description="현장 사진 (다중 선택 가능)"),
    notice: UploadFile = File(default=None, description="(선택) 점검 지시·공고문"),
):
    api_key = os.environ.get("UPSTAGE_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "UPSTAGE_API_KEY 환경변수가 설정되지 않았습니다.",
                "hint": "실행 전 export UPSTAGE_API_KEY=<발급키> 또는 .env 파일에 설정하세요.",
            },
        )

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "step": "접수 완료",
        "result": None,
        "error": None,
        "photo_paths": [],
    }

    tmpdir = tempfile.mkdtemp(prefix="mabc_job_")

    # 문서 저장
    doc_path = _safe_save_path(tmpdir, document.filename)
    doc_bytes = await document.read()
    with open(doc_path, "wb") as f:
        f.write(doc_bytes)

    # 사진 저장
    photo_paths: list[str] = []
    for photo in photos:
        p = _safe_save_path(tmpdir, photo.filename)
        data = await photo.read()
        with open(p, "wb") as f:
            f.write(data)
        photo_paths.append(p)
    jobs[job_id]["photo_paths"] = photo_paths

    # 공고문 저장 (pipeline에는 전달하지 않음 — 추후 확장용)
    if notice is not None:
        notice_path = os.path.join(tmpdir, "notice")
        data = await notice.read()
        with open(notice_path, "wb") as f:
            f.write(data)

    def _run_pipeline():
        try:
            jobs[job_id]["status"] = "running"
            jobs[job_id]["progress"] = 5
            jobs[job_id]["step"] = "문서 판독 중"

            result = run_pipeline(
                file_path=doc_path,
                photo_files=photo_paths if photo_paths else None,
                offline=False,
            )

            jobs[job_id]["result"] = result
            jobs[job_id]["status"] = "done"
            jobs[job_id]["progress"] = 100
            jobs[job_id]["step"] = "완료"
        except Exception as exc:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = str(exc)
            jobs[job_id]["step"] = "오류 발생"
            jobs[job_id]["progress"] = 100

    background_tasks.add_task(_run_pipeline)

    return {
        "job_id": job_id,
        "status": "queued",
        "message": "검사를 시작했습니다. 진행 상황은 GET /jobs/{job_id} 에서 확인하세요.",
    }


# ── POST /jobs/demo ──────────────────────────────────────────────────────────
@app.post("/jobs/demo", include_in_schema=False)
async def create_demo_job(background_tasks: BackgroundTasks):
    """샘플 보고서와 사진 2장을 자동으로 넣어 검사를 실행한다. (첫 방문 체험용)"""
    api_key = os.environ.get("UPSTAGE_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "UPSTAGE_API_KEY 환경변수가 설정되지 않았습니다.",
                "hint": "실행 전 export UPSTAGE_API_KEY=<발급키> 또는 .env 파일에 설정하세요.",
            },
        )

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "step": "접수 완료",
        "result": None,
        "error": None,
        "photo_paths": [],
    }

    tmpdir = tempfile.mkdtemp(prefix="mabc_demo_")

    try:
        doc_path, photo_paths = _build_demo_job(tmpdir)
        jobs[job_id]["photo_paths"] = photo_paths
    except FileNotFoundError as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)
        jobs[job_id]["step"] = "데모 자산 누락"
        jobs[job_id]["progress"] = 100
        return {
            "job_id": job_id,
            "status": "error",
            "error": str(e),
        }

    def _run_pipeline():
        try:
            jobs[job_id]["status"] = "running"
            jobs[job_id]["progress"] = 5
            jobs[job_id]["step"] = "문서 판독 중"

            result = run_pipeline(
                file_path=doc_path,
                photo_files=photo_paths,
                offline=False,
            )

            jobs[job_id]["result"] = result
            jobs[job_id]["status"] = "done"
            jobs[job_id]["progress"] = 100
            jobs[job_id]["step"] = "완료"
        except Exception as exc:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = str(exc)
            jobs[job_id]["step"] = "오류 발생"
            jobs[job_id]["progress"] = 100

    background_tasks.add_task(_run_pipeline)

    return {
        "job_id": job_id,
        "status": "queued",
        "message": "샘플 보고서로 검사를 시작했습니다. 진행 상황은 GET /jobs/{job_id} 에서 확인하세요.",
    }


# ── GET /jobs/{job_id} ───────────────────────────────────────────────────────
@app.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(
            status_code=404,
            detail={"error": f"존재하지 않는 작업 ID입니다: {job_id}"},
        )
    job = jobs[job_id]
    resp: dict = {
        "job_id": job_id,
        "status": job["status"],
        "progress": job["progress"],
        "step": job["step"],
        "error": job.get("error"),
    }
    # 완료된 작업이면 result 포함
    if job["status"] == "done" and job.get("result") is not None:
        resp["result"] = job["result"]
    return resp


# ── GET /jobs/{job_id}/report ────────────────────────────────────────────────
@app.get("/jobs/{job_id}/report")
async def get_job_report(job_id: str):
    if job_id not in jobs:
        raise HTTPException(
            status_code=404,
            detail={"error": f"존재하지 않는 작업 ID입니다: {job_id}"},
        )
    job = jobs[job_id]
    if job["status"] != "done":
        raise HTTPException(
            status_code=400,
            detail={
                "error": "아직 완료되지 않았습니다.",
                "current_status": job["status"],
                "step": job["step"],
            },
        )

    result = job["result"]
    if result is None:
        raise HTTPException(status_code=500, detail={"error": "결과가 없습니다."})

    # photo_section의 각 match에 photo_n(1-based)을 부여
    photo_paths = job.get("photo_paths", [])
    if photo_paths and "photo_section" in result and "matches" in result["photo_section"]:
        for m in result["photo_section"]["matches"]:
            pf = m.get("photo_file", "")
            if pf:
                basename = os.path.basename(pf)
                for i, path in enumerate(photo_paths, 1):
                    if os.path.basename(path) == basename:
                        m["photo_n"] = i
                        break

    return result


# ── GET /jobs/{job_id}/photos/{n} ────────────────────────────────────────────
@app.get("/jobs/{job_id}/photos/{photo_n}")
async def get_job_photo(job_id: str, photo_n: int):
    """업로드된 사진 n번(1-based)을 서빙한다."""
    if job_id not in jobs:
        raise HTTPException(
            status_code=404,
            detail={"error": f"존재하지 않는 작업 ID입니다: {job_id}"},
        )
    job = jobs[job_id]
    photo_paths: list[str] = job.get("photo_paths", [])
    if photo_n < 1 or photo_n > len(photo_paths):
        raise HTTPException(
            status_code=404,
            detail={
                "error": f"사진 번호가 범위를 벗어났습니다: {photo_n} (전체 {len(photo_paths)}장)",
            },
        )
    photo_path = photo_paths[photo_n - 1]
    if not os.path.isfile(photo_path):
        raise HTTPException(status_code=404, detail={"error": "사진 파일을 찾을 수 없습니다."})
    media_type, _ = mimetypes.guess_type(photo_path)
    return FileResponse(photo_path, media_type=media_type or "application/octet-stream")


# ── GET / (정적 index.html) ──────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = STATIC_DIR / "index.html"
    if not html_path.exists():
        return HTMLResponse(
            content="<html><body><h1>index.html을 찾을 수 없습니다</h1></body></html>",
            status_code=500,
        )
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


# ── GET /inspect/demo ────────────────────────────────────────────────────────
@app.get("/inspect/demo", include_in_schema=False)
async def inspect_demo():
    """데모 사진 3장으로 사진 기반 안전 점검 체험을 제공한다. (캐시 재생)

    UPSTAGE_API_KEY가 없어도 inspect_result(점검 엔진 결과)는 항상 반환한다.
    draft_md는 키가 있을 때만 생성한다.
    """
    demo_dir = ASSETS_DIR / "vision" / "demo_photos"
    photo_names = ["r1_l3_pipe.jpg", "r1_l2_loading.jpg", "r1_l1_electrical.jpg"]
    photo_files = [str(demo_dir / name) for name in photo_names]
    missing = [pf for pf in photo_files if not os.path.isfile(pf)]
    if missing:
        raise HTTPException(
            status_code=500,
            detail={"error": "데모 사진 누락", "missing": missing},
        )

    inspect_result = inspect_photos(photo_files)

    api_key = os.environ.get("UPSTAGE_API_KEY")
    draft_md: Optional[str] = None
    if api_key:
        draft_md = generate_draft(inspect_result)

    return {
        "status": "ok",
        "inspect_result": inspect_result,
        "draft_md": draft_md,
    }


# ── GET /watch/demo/annotated/{n} ─────────────────────────────────────────────
@app.get("/watch/demo/annotated/{n}", include_in_schema=False)
async def watch_demo_annotated(n: int):
    """데모 관제 사진 n번째(1-based)의 annotated 이미지를 FileResponse로 서빙.

    /watch/demo 결과의 photo_names 순서(r1_l3_pipe, r1_l2_loading, r1_l1_electrical)를 따른다.
    """
    if n < 1 or n > 3:
        raise HTTPException(
            status_code=404,
            detail={"error": f"사진 번호가 범위를 벗어났습니다: {n} (전체 3장)"},
        )
    photo_names = ["r1_l3_pipe.jpg", "r1_l2_loading.jpg", "r1_l1_electrical.jpg"]
    annotated_name = f"annotated_{photo_names[n - 1]}"
    annotated_path = ASSETS_DIR / "vision" / "demo_photos" / annotated_name
    if not annotated_path.is_file():
        raise HTTPException(status_code=404, detail={"error": "주석 이미지를 찾을 수 없습니다."})
    media_type, _ = mimetypes.guess_type(str(annotated_path))
    return FileResponse(str(annotated_path), media_type=media_type or "image/jpeg")


# ── GET /watch/demo ──────────────────────────────────────────────────────────
@app.get("/watch/demo", include_in_schema=False)
async def watch_demo():
    """관제 데모: demo_photos 3장으로 사진 기반 위험 탐지 체험.

    inspect_result + 각 사진별 annotated 경로 포함.
    """
    demo_dir = ASSETS_DIR / "vision" / "demo_photos"
    photo_names = ["r1_l3_pipe.jpg", "r1_l2_loading.jpg", "r1_l1_electrical.jpg"]
    photo_files = [str(demo_dir / name) for name in photo_names]
    missing = [pf for pf in photo_files if not os.path.isfile(pf)]
    if missing:
        raise HTTPException(
            status_code=500,
            detail={"error": "데모 사진 누락", "missing": missing},
        )

    inspect_result = inspect_photos(photo_files)

    # annotated 경로가 없는 경우 즉시 생성
    for photo in inspect_result["photos"]:
        if not photo.get("annotated"):
            src = demo_dir / photo["photo"]
            if src.is_file():
                out_name = f"annotated_{photo['photo']}"
                out_path = str(demo_dir / out_name)
                annotate_image_with_risk_badge(
                    str(src),
                    photo["detections"],
                    out_path,
                    risk_level=photo["risk_level"],
                )
                photo["annotated"] = out_path

    return {
        "status": "ok",
        "inspect_result": inspect_result,
    }


# ── POST /watch ──────────────────────────────────────────────────────────────
@app.post("/watch")
async def create_watch_job(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(default=None, description="영상 파일 (mp4)"),
    files: List[UploadFile] = File(default=[], description="사진 파일들"),
):
    """사진들 또는 영상 1개를 업로드하여 위험 탐지를 실행한다.

    - photos: 여러 장 업로드 시 각각 inspect_photos 로 분석.
    - video: mp4 업로드 시 1fps·최대24프레임·640px 샘플링 후 각 프레임 분석.
    결과 JSON에 detections(box 포함)·annotated 경로 포함.

    Returns:
        {"job_id": ..., "status": "queued", "message": "..."}
    """
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "step": "접수 완료",
        "result": None,
        "error": None,
        "photo_paths": [],
        "video_path": None,
        "frame_paths": [],
    }

    tmpdir = tempfile.mkdtemp(prefix="mabc_watch_")

    frame_paths: list[str] = []

    # 영상 처리 (우선순위: video가 있으면 영상만 처리)
    if video is not None:
        video_path = os.path.join(tmpdir, "upload_video.mp4")
        data = await video.read()
        with open(video_path, "wb") as f:
            f.write(data)
        jobs[job_id]["video_path"] = video_path

        frames_dir = os.path.join(tmpdir, "frames")
        try:
            frame_paths = extract_frames(video_path, frames_dir, max_frames=24, target_width=640)
            jobs[job_id]["frame_paths"] = frame_paths
        except Exception as e:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = f"영상 프레임 추출 실패: {str(e)}"
            jobs[job_id]["step"] = "프레임 추출 오류"
            jobs[job_id]["progress"] = 100
            return {
                "job_id": job_id,
                "status": "error",
                "error": f"영상 프레임 추출 실패: {str(e)}",
            }

    # 사진 처리
    photo_paths: list[str] = []
    for f in files:
        p = _safe_save_path(tmpdir, f.filename)
        data = await f.read()
        with open(p, "wb") as out:
            out.write(data)
        photo_paths.append(p)
    jobs[job_id]["photo_paths"] = photo_paths

    # 분석 대상: 영상 프레임이 있으면 프레임들, 없으면 사진들
    targets = frame_paths if frame_paths else photo_paths

    def _run_watch():
        try:
            jobs[job_id]["status"] = "running"
            jobs[job_id]["progress"] = 20
            jobs[job_id]["step"] = "영상 판독 중" if frame_paths else "사진 점검 중"

            inspect_result = inspect_photos(targets)

            # 각 사진/프레임별 annotated 생성
            for photo in inspect_result["photos"]:
                if not photo.get("annotated"):
                    src = Path(photo["photo_path"]) if os.path.isfile(photo["photo_path"]) else None
                    if src is None:
                        # 데모 사진에서 찾기
                        basename = photo["photo"]
                        candidate = ASSETS_DIR / "vision" / "demo_photos" / basename
                        if candidate.is_file():
                            src = candidate
                    if src and src.is_file():
                        out_name = f"annotated_{photo['photo']}"
                        out_path = os.path.join(tmpdir, out_name)
                        annotate_image_with_risk_badge(
                            str(src),
                            photo["detections"],
                            out_path,
                            risk_level=photo["risk_level"],
                        )
                        photo["annotated"] = out_path

            jobs[job_id]["result"] = {
                "inspect_result": inspect_result,
            }
            jobs[job_id]["status"] = "done"
            jobs[job_id]["progress"] = 100
            jobs[job_id]["step"] = "완료"
        except Exception as exc:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = str(exc)
            jobs[job_id]["step"] = "오류 발생"
            jobs[job_id]["progress"] = 100

    background_tasks.add_task(_run_watch)

    return {
        "job_id": job_id,
        "status": "queued",
        "message": "영상·사진 분석을 시작했습니다. 진행 상황은 GET /jobs/{job_id} 에서 확인하세요.",
    }


# ── GET /watch/video ──────────────────────────────────────────────────────────
@app.get("/watch/video", include_in_schema=False)
async def watch_video():
    """관제 데모 영상(demo_video.mp4)을 FileResponse로 서빙.
    
    Range 요청 지원 (FileResponse 기본 동작).
    """
    video_path = ASSETS_DIR / "vision" / "demo_video.mp4"
    if not video_path.is_file():
        raise HTTPException(status_code=500, detail={"error": "관제 영상이 없습니다."})
    media_type, _ = mimetypes.guess_type(str(video_path))
    return FileResponse(str(video_path), media_type=media_type or "video/mp4")


# ── GET /watch/video/timeline ──────────────────────────────────────────────────
@app.get("/watch/video/timeline", include_in_schema=False)
async def watch_video_timeline():
    """demo_video.mp4 기반 타임라인(demo_video_timeline.json)을 서빙.
    
    build_video_timeline.py 로 생성된 실측 데이터.
    """
    timeline_path = ASSETS_DIR / "vision" / "demo_video_timeline.json"
    if not timeline_path.is_file():
        raise HTTPException(status_code=500, detail={"error": "타임라인 데이터가 없습니다. build_video_timeline.py를 먼저 실행하세요."})
    return json.loads(timeline_path.read_text(encoding="utf-8"))


@app.get("/jobs/{job_id}/annotated/{frame_n}")
async def get_job_annotated(job_id: str, frame_n: int):
    """분석 완료된 작업의 n번째 프레임/사진에 대한 annotated(주석) 이미지를 서빙.

    n은 1-based 인덱스. inspect_result.photos[n-1].annotated 경로를 반환.
    """
    if job_id not in jobs:
        raise HTTPException(
            status_code=404,
            detail={"error": f"존재하지 않는 작업 ID입니다: {job_id}"},
        )
    job = jobs[job_id]
    if job["status"] != "done":
        raise HTTPException(
            status_code=400,
            detail={
                "error": "아직 완료되지 않았습니다.",
                "current_status": job["status"],
                "step": job["step"],
            },
        )

    result = job.get("result")
    if result is None or "inspect_result" not in result:
        raise HTTPException(status_code=500, detail={"error": "결과가 없습니다."})

    photos = result["inspect_result"].get("photos", [])
    if frame_n < 1 or frame_n > len(photos):
        raise HTTPException(
            status_code=404,
            detail={
                "error": f"프레임/사진 번호가 범위를 벗어났습니다: {frame_n} (전체 {len(photos)}개)"
            },
        )

    photo = photos[frame_n - 1]
    annotated_path = photo.get("annotated")
    if not annotated_path or not os.path.isfile(annotated_path):
        raise HTTPException(status_code=404, detail={"error": "주석 이미지를 찾을 수 없습니다."})

    media_type, _ = mimetypes.guess_type(annotated_path)
    return FileResponse(annotated_path, media_type=media_type or "image/jpeg")


# ── POST /inspect ────────────────────────────────────────────────────────────
@app.post("/inspect")
async def create_inspect_job(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(..., description="현장 사진 (다중 선택 가능)"),
    gauge: bool = False,
):
    """사진 여러 장으로 사진 기반 안전 점검을 실행한다.

    결과 JSON에 사진별 카드 + 종합 + draft_report(md)를 포함한다.
    (초안 생성에는 UPSTAGE_API_KEY가 필요하며, 없으면 inspect_result만 반환한다.)
    """
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "step": "접수 완료",
        "result": None,
        "error": None,
        "photo_paths": [],
    }

    tmpdir = tempfile.mkdtemp(prefix="mabc_inspect_")
    photo_paths: list[str] = []

    for f in files:
        p = _safe_save_path(tmpdir, f.filename)
        data = await f.read()
        with open(p, "wb") as out:
            out.write(data)
        photo_paths.append(p)

    jobs[job_id]["photo_paths"] = photo_paths

    def _run_inspect():
        try:
            jobs[job_id]["status"] = "running"
            jobs[job_id]["progress"] = 20
            jobs[job_id]["step"] = "사진 점검 중"

            inspect_result = inspect_photos(photo_paths, gauge=gauge)

            api_key = os.environ.get("UPSTAGE_API_KEY")
            draft_md: Optional[str] = None
            if api_key:
                jobs[job_id]["step"] = "보고서 초안 생성 중"
                draft_md = generate_draft(inspect_result)
            else:
                draft_md = None

            jobs[job_id]["result"] = {
                "inspect_result": inspect_result,
                "draft_md": draft_md,
            }
            jobs[job_id]["status"] = "done"
            jobs[job_id]["progress"] = 100
            jobs[job_id]["step"] = "완료"
        except Exception as exc:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = str(exc)
            jobs[job_id]["step"] = "오류 발생"
            jobs[job_id]["progress"] = 100

    background_tasks.add_task(_run_inspect)

    return {
        "job_id": job_id,
        "status": "queued",
        "message": "점검 작업을 시작했습니다. 진행 상황은 GET /jobs/{job_id} 에서 확인하세요.",
    }
