import os
import uuid
import tempfile
from pathlib import Path
from typing import List

from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse

from service.core.pipeline import run_pipeline

app = FastAPI(title="현장 보고 검증 게이트")

# ── 메모리 Job 저장고 ────────────────────────────────────────────────────────
jobs: dict[str, dict] = {}

STATIC_DIR = Path(__file__).resolve().parent.parent / "web"


# ── 경로 안전화 헬퍼 ─────────────────────────────────────────────────────────
def _safe_save_path(tmpdir: str, original_filename: str) -> str:
    """원본 파일명을 보존하되 경로 안전화만 수행하여 저장 경로를 반환한다.

    - 디렉터리 구분자(`/`, `\\`) 및 널문자 제거
    - 한글 등 비ASCII 문자 보존
    - 확장자 보존
    - 이름 충돌 시 뒤에 `_1`, `_2` 등 접미사 추가
    """
    # 널문자 제거
    name = original_filename.replace("\x00", "")
    # 디렉터리 구분자 제거
    name = name.replace("/", "_").replace("\\", "_")
    # 경로 트래버설 방지: '..' 제거
    name = name.replace("..", "")
    # 빈 이름이 되면 기본값 사용
    if not name.strip():
        name = "unnamed"
    # 중복 처리
    base_path = os.path.join(tmpdir, name)
    if not os.path.exists(base_path):
        return base_path
    # 확장자 분리
    base, ext = os.path.splitext(name)
    counter = 1
    while True:
        new_name = f"{base}_{counter}{ext}"
        new_path = os.path.join(tmpdir, new_name)
        if not os.path.exists(new_path):
            return new_path
        counter += 1


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
    }

    tmpdir = tempfile.mkdtemp(prefix="mabc_job_")

    # 문서 저장
    doc_path = _safe_save_path(tmpdir, document.filename)
    doc_bytes = await document.read()
    with open(doc_path, "wb") as f:
        f.write(doc_bytes)

    # 사진 저장
    photo_paths: list[str] = []
    for i, photo in enumerate(photos):
        p = _safe_save_path(tmpdir, photo.filename)
        data = await photo.read()
        with open(p, "wb") as f:
            f.write(data)
        photo_paths.append(p)

    # 공고문 저장 (pipeline에는 전달하지 않음 — 추후 확장용)
    notice_path = None
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


# ── GET /jobs/{job_id} ───────────────────────────────────────────────────────
@app.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(
            status_code=404,
            detail={"error": f"존재하지 않는 작업 ID입니다: {job_id}"},
        )
    job = jobs[job_id]
    return {
        "job_id": job_id,
        "status": job["status"],
        "progress": job["progress"],
        "step": job["step"],
        "error": job.get("error"),
    }


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
    return job["result"]


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
