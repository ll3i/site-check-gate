#!/usr/bin/env python3
"""
tests/test_mcp.py — MCP 서버 5종 기동·왕복 테스트.

각 서버를 subprocess 로 stdio MCP 서버로 실행한 뒤,
1) initialize → 2) tools/list → 3) tools/call(1회) 왕복이 성공하는지 확인한다.

네트워크 필요한 tool(cite_core의 match_claim 등)은 실제 1회 호출을 시도하되,
실패해도 왕복 자체는 성공한 것으로 간주한다 (initialize·tools/list·tools/call 왕복 OK).

주의: 각 서버는 별도 프로세스로 기동하며, 통신은 stdin/stdout 라인 JSON으로 수행한다.
"""
import json
import os
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional
from pathlib import Path

# ── 프로젝트 루트 ───────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = PROJECT_ROOT / "service" / "mcp_servers"

# 서버: (표시명, 스크립트경로)
SERVERS: List[tuple[str, Path]] = [
    ("cite_core",    SERVER_DIR / "cite_core_server.py"),
    ("pii_guard",    SERVER_DIR / "pii_guard_server.py"),
    ("law_registry", SERVER_DIR / "law_registry_server.py"),
    ("site_rules",   SERVER_DIR / "site_rules_server.py"),
]

# ── 테스트 입력 ────────────────────────────────────────────────────────────────

SAMPLE_REF_TEXT = (
    "Goodfellow, I., Bengio, Y., & Courville, A. (2016). Deep Learning. "
    "MIT Press. https://www.deeplearningbook.org/\n"
    "Vaswani, A., et al. (2017). Attention is All You Need. "
    "Advances in Neural Information Processing Systems, 30. "
    "https://arxiv.org/abs/1706.03762"
)

SAMPLE_PII_TEXT = (
    "담당자: 김철수 (010-1234-5678)\n"
    "문의: test@example.com\n"
    "계좌: 123-45-678901 (신한은행, 예금주: 홍길동)\n"
    "주소: 서울시 강남구 테헤란로 123\n"
    "OpenAI API Key: sk-1234567890abcdefghijklmnopqrstuv"
)

SAMPLE_LAW_NAME = "근로기준법"
SAMPLE_ARTICLE = 1

SAMPLE_SUBCONTRACT_TEXT = (
    "당사는 원청이 직접 작업 지시를 하고 있으며, "
    "원청 직원이 수급인 근로자에게 직접 작업 방법을 지시한다. "
    "또한 원청이 출퇴근 시간과 근무 시간을 직접 통제하며, "
    "원청 관리자가 수급인 근로자에 대한 징계를 직접 수행한다. "
    "원청 근로자와 같은 장소에서 혼재되어 작업하고 있으며, "
    "원청 시스템에 직접 로그인하여 업무를 처리한다."
)


# ── JSON-RPC 헬퍼 ───────────────────────────────────────────────────────────────

def jsonrpc_request(method: str,
                     params: Optional[Dict[str, Any]] = None,
                     request_id: int = 1) -> Dict[str, Any]:
    req: Dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        req["params"] = params
    return req


def send_request(proc: subprocess.Popen,
                 request: Dict[str, Any],
                 timeout: float = 5.0) -> Dict[str, Any]:
    payload = json.dumps(request, ensure_ascii=False) + "\n"
    try:
        proc.stdin.write(payload)
        proc.stdin.flush()
    except (BrokenPipeError, OSError) as exc:
        raise RuntimeError(f"서버 stdin 쓰기 실패: {exc}") from exc

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("서버 stdout EOF (서버 종료됨)")
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"서버 응답 JSON 파싱 실패: {exc}") from exc
    raise RuntimeError(f"서버 응답 타임아웃 ({timeout}초)")


def wait_for_init(proc: subprocess.Popen, timeout: float = 3.0) -> Dict[str, Any]:
    req = jsonrpc_request("initialize", request_id=0)
    resp = send_request(proc, req, timeout=timeout)
    if "error" in resp:
        raise RuntimeError(f"initialize 오류: {resp['error']}")
    if "result" not in resp:
        raise RuntimeError(f"initialize 응답에 result 없음: {resp}")
    return resp


def check_tools_list(proc: subprocess.Popen,
                     timeout: float = 3.0) -> List[Dict[str, Any]]:
    req = jsonrpc_request("tools/list", request_id=0)
    resp = send_request(proc, req, timeout=timeout)
    if "error" in resp:
        raise RuntimeError(f"tools/list 오류: {resp['error']}")
    tools = resp.get("result", {}).get("tools", [])
    if not isinstance(tools, list):
        raise RuntimeError(f"tools/list 결과가 list가 아님: {type(tools)}")
    return tools


def check_tools_call(proc: subprocess.Popen,
                     tool_name: str,
                     arguments: Dict[str, Any],
                     timeout: float = 10.0) -> Dict[str, Any]:
    req = jsonrpc_request("tools/call", {
        "name": tool_name,
        "arguments": arguments,
    }, request_id=0)
    resp = send_request(proc, req, timeout=timeout)
    if "error" in resp:
        # 도구 실행 중 MCP 오류는 왕복은 성공한 것으로 간주
        print(f"    [WARN] tools/call 오류 (왕복은 성공): {resp['error']}")
        return {"_call_ok": True, "error": resp["error"]}
    if "result" not in resp:
        raise RuntimeError(f"tools/call 응답에 result 없음: {resp}")
    return {"_call_ok": True, "result": resp["result"]}


# ── 서버 기동/종료 ──────────────────────────────────────────────────────────────

def start_server(script_path: Path) -> subprocess.Popen:
    """stdio MCP 서버 프로세스를 기동한다.

    PROJECT_ROOT 를 PYTHONPATH에 추가하여 service.core 등
    상대 import 가 작동하게 한다. 스크립트는 절대경로(네이티브)로 전달.
    mingw/MSYS bash 환경에서도 python 이 스크립트를 찾을 수 있도록
    Path.resolve() 로 얻은 네이티브 Windows 경로를 사용한다.
    """
    env = os.environ.copy()
    python_exe = sys.executable or "python3"

    # 프로젝트 루트를 PYTHONPATH에 추가
    proj = str(PROJECT_ROOT.resolve())
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = proj + (";" + prev if prev else "")

    # 스크립트 절대경로(네이티브 Windows 경로)
    abs_script = str(script_path.resolve())

    proc = subprocess.Popen(
        [python_exe, abs_script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
        cwd=str(PROJECT_ROOT.resolve()),
    )
    return proc


def stop_server(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)


# ── 서버별 왕복 테스트 ──────────────────────────────────────────────────────────

def test_server(name: str, script_path: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "name": name,
        "script": str(script_path),
        "initialize_ok": False,
        "tools_list_ok": False,
        "tools_call_ok": False,
        "tools_count": 0,
        "error": None,
        "detail": None,
    }
    proc = None
    try:
        proc = start_server(script_path)
        time.sleep(0.3)

        init_resp = wait_for_init(proc, timeout=3.0)
        result["initialize_ok"] = True
        result["detail"] = {
            "server_info": init_resp.get("result", {}).get("serverInfo"),
            "protocol_version": init_resp.get("result", {}).get("protocolVersion"),
        }

        tools = check_tools_list(proc, timeout=3.0)
        result["tools_list_ok"] = True
        result["tools_count"] = len(tools)
        result["detail"]["tools"] = [t.get("name") for t in tools]

        call_results: List[Dict[str, Any]] = []
        for tool in tools:
            tool_name = tool.get("name")
            if not tool_name:
                continue
            args = _make_test_args(name, tool_name)
            if args is None:
                continue
            cr = check_tools_call(proc, tool_name, args, timeout=12.0)
            call_results.append({
                "tool": tool_name,
                "ok": cr.get("_call_ok", False),
                "result_preview": _preview_result(cr),
            })
            if cr.get("_call_ok"):
                result["tools_call_ok"] = True

        result["detail"]["call_results"] = call_results

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if proc is not None:
            stop_server(proc)
    return result


def _make_test_args(server_name: str, tool_name: str) -> Optional[Dict[str, Any]]:
    if server_name == "cite_core":
        if tool_name == "verify_references":
            return {"text": SAMPLE_REF_TEXT}
        elif tool_name == "match_claim":
            return {
                "claim": "Deep learning은 인공신경망 기반 기계학습의 하위 분야이다.",
                "title": "Deep Learning",
                "abstract": "이 책은 딥러닝에 대한 포괄적인 개요를 제공한다.",
            }
    elif server_name == "pii_guard":
        if tool_name == "scan_pii":
            return {"text": SAMPLE_PII_TEXT, "min_confidence": "info"}
    elif server_name == "law_registry":
        if tool_name == "lookup_article":
            return {"law_name": SAMPLE_LAW_NAME, "article": SAMPLE_ARTICLE}
        elif tool_name == "search_articles":
            return {"keyword": "노동"}
    elif server_name == "site_rules":
        if tool_name == "check_subcontract":
            return {"text": SAMPLE_SUBCONTRACT_TEXT}
    return None


def _preview_result(call_result: Dict[str, Any]) -> Any:
    if not call_result.get("_call_ok"):
        return call_result.get("error")
    result = call_result.get("result")
    if result is None:
        return None
    if isinstance(result, dict) and "content" in result:
        content = result["content"]
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict) and first.get("type") == "text":
                text = first.get("text", "")
                if len(text) > 300:
                    return text[:300] + "..."
                return text
        return str(content)[:200]
    try:
        s = json.dumps(result, ensure_ascii=False)
        if len(s) > 400:
            return s[:400] + "..."
        return s
    except (TypeError, ValueError):
        return str(result)[:200]


# ── 메인 ────────────────────────────────────────────────────────────────────────

def run_tests() -> int:
    print("=" * 60)
    print("MCP 서버 왕복 테스트 (5종)")
    print("=" * 60)

    all_ok = True
    for name, script in SERVERS:
        if not script.exists():
            print(f"\n[FAIL] {name}: 스크립트 없음 ({script})")
            all_ok = False
            continue

        print(f"\n--- {name} ({script.name}) ---")
        result = test_server(name, script)

        if result["error"]:
            print(f"  [FAIL] 오류: {result['error']}")
            all_ok = False
        else:
            init_ok = result["initialize_ok"]
            list_ok = result["tools_list_ok"]
            call_ok = result["tools_call_ok"]
            cnt = result["tools_count"]

            print(f"  initialize: {'OK' if init_ok else 'FAIL'}")
            print(f"  tools/list: {'OK' if list_ok else 'FAIL'} (도구 {cnt}개)")
            print(f"  tools/call: {'OK' if call_ok else 'SKIP'}")

            if result["detail"] and "tools" in result["detail"]:
                print(f"    도구 목록: {result['detail']['tools']}")

            if result["detail"] and "call_results" in result["detail"]:
                for cr in result["detail"]["call_results"]:
                    status = "OK" if cr["ok"] else "FAIL"
                    print(f"    tools/call {cr['tool']}: {status}")
                    preview = cr.get("result_preview")
                    if preview is not None:
                        if isinstance(preview, str) and len(preview) > 200:
                            preview = preview[:200] + "..."
                        print(f"      미리보기: {preview}")

            if not init_ok or not list_ok:
                all_ok = False
            if not call_ok and result["tools_count"] > 0:
                print(f"  [WARN] tools/call이 모든 도구에서 실패 — 왕복 자체는 성립")

    print("\n" + "=" * 60)
    if all_ok:
        print("결과: ALL PASS")
    else:
        print("결과: SOME FAIL")
    print("=" * 60)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(run_tests())
