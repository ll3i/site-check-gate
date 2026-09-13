#!/usr/bin/env python
"""mabc-2026-final 서비스 기동 스크립트"""
import os, subprocess, sys, time

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

api_key = os.environ.get("UPSTAGE_API_KEY")
if not api_key:
    print("오류: UPSTAGE_API_KEY 환경변수가 설정되지 않았습니다.", file=sys.stderr)
    sys.exit(1)

port = int(os.environ.get("PORT", "8765"))
cmd = [
    sys.executable, "-m", "uvicorn",
    "service.api.app:app",
    "--host", "127.0.0.1",
    "--port", str(port),
    "--log-level", "info",
]
print(f"Starting: {' '.join(cmd)}")
proc = subprocess.run(cmd)
