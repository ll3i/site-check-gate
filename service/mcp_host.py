#!/usr/bin/env python3
"""
mcp_host.py — MCP stdio 서버 호스트.

mcpServers.json(레포 루트)을 읽어 설정된 서버들을 stdio 프로세스로 기동·연결한다.
각 서버는 별도 subprocess 로 실행되며, 통신은 stdin/stdout 라인 JSON(JSON-RPC 2.0)으로 한다.

주요 인터페이스:
  - start_all(): mcpServers.json 의 enabled:true 서버 전부를 기동
  - list_all_tools(): 기동된 모든 서버의 tools/list 결과를 집계 반환
  - call(server_name, tool_name, args): 특정 서버의 tools/call 호출
  - stop_all(): 모든 서버 프로세스 종료
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── 경로 ─────────────────────────────────────────────────────────────────────────

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
CONFIG_PATH = PROJECT_ROOT / "mcpServers.json"

# ── 설정 로딩 ────────────────────────────────────────────────────────────────────

def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """mcpServers.json 을 읽어 파싱된 dict를 반환한다."""
    p = path or CONFIG_PATH
    if not p.is_file():
        raise FileNotFoundError(f"mcpServers.json 을 찾을 수 없음: {p}")
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def list_enabled_servers(config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """설정에서 enabled:true 인 서버 목록만 반환."""
    cfg = config or load_config()
    servers = cfg.get("mcpServers", {})
    enabled: List[Dict[str, Any]] = []
    for name, spec in servers.items():
        if isinstance(spec, dict) and spec.get("enabled", False):
            entry: Dict[str, Any] = {"name": name}
            entry.update(spec)
            enabled.append(entry)
    return enabled


# ── 서버 프로세스 관리 ───────────────────────────────────────────────────────────

class MCPHost:
    """mcpServers.json 기반 stdio MCP 서버 호스트."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self._config = config or load_config()
        self._procs: Dict[str, subprocess.Popen] = {}   # name → Popen
        self._tools_cache: Optional[List[Dict[str, Any]]] = None
        self._python_exe = sys.executable or "python3"

    # ── 기동/종료 ──────────────────────────────────────────────────────────────

    def start_all(self, timeout_per_server: float = 5.0) -> Dict[str, Any]:
        """mcpServers.json 의 enabled:true 서버 전부를 stdio 프로세스로 기동.

        반환: {"started": [...], "failed": [...]}
        """
        servers = list_enabled_servers(self._config)
        started: List[str] = []
        failed: List[Dict[str, str]] = []

        for spec in servers:
            name = spec["name"]
            if name in self._procs:
                started.append(name)
                continue
            try:
                proc = self._start_server(spec)
                self._procs[name] = proc
                # 초기화 핸드셰이크 대기
                self._wait_for_ready(proc, timeout=timeout_per_server)
                started.append(name)
            except Exception as exc:
                failed.append({"name": name, "error": f"{type(exc).__name__}: {exc}"})

        return {"started": started, "failed": failed}

    def _start_server(self, spec: Dict[str, Any]) -> subprocess.Popen:
        """단일 서버 프로세스를 기동."""
        args = spec.get("args", [])
        # command 필드가 있으면 사용, 없으면 python
        cmd = spec.get("command", self._python_exe)
        if isinstance(cmd, str):
            cmd = [cmd]
        cmd = list(cmd) + [str(PROJECT_ROOT / a) if not Path(a).is_absolute() else a for a in args]

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        # 프로젝트 루트를 PYTHONPATH에 추가
        proj = str(PROJECT_ROOT.resolve())
        prev = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = proj + (";" + prev if prev else "")

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=env,
            cwd=str(PROJECT_ROOT.resolve()),
        )
        return proc

    def _wait_for_ready(self, proc: subprocess.Popen, timeout: float = 5.0) -> None:
        """서버가 initialize 핸드셰이크에 응답할 때까지 대기."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                resp = self._send_jsonrpc(proc, {"jsonrpc": "2.0", "id": 0, "method": "initialize"}, timeout=1.0)
                if resp is not None and "result" in resp:
                    return
            except Exception:
                pass
            time.sleep(0.1)
        raise RuntimeError(f"서버 초기화 타임아웃 ({(deadline - time.monotonic()):.1f}초 남음)")

    def stop_all(self) -> List[str]:
        """모든 서버 프로세스를 종료. 종료된 서버 이름 목록 반환."""
        stopped: List[str] = []
        for name, proc in list(self._procs.items()):
            try:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=2)
                stopped.append(name)
            except Exception:
                pass
            finally:
                self._procs.pop(name, None)
        self._tools_cache = None
        return stopped

    # ── 도구 목록 ──────────────────────────────────────────────────────────────

    def list_all_tools(self) -> List[Dict[str, Any]]:
        """기동된 모든 서버의 tools/list 결과를 집계하여 반환.

        각 도구 dict에 "server" 키가 추가된다 (어느 서버 소속인지).
        """
        self._tools_cache = []
        for name, proc in self._procs.items():
            if proc.poll() is not None:
                continue
            try:
                resp = self._send_jsonrpc(proc, {"jsonrpc": "2.0", "id": 0, "method": "tools/list"}, timeout=3.0)
                if resp and "result" in resp:
                    tools = resp["result"].get("tools", [])
                    for t in tools:
                        entry = dict(t)
                        entry["server"] = name
                        self._tools_cache.append(entry)
            except Exception:
                pass
        return list(self._tools_cache)

    # ── 도구 호출 ──────────────────────────────────────────────────────────────

    def call(self, server_name: str, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """특정 서버의 tools/call 을 호출하고 응답을 반환.

        반환: {"ok": bool, "result": ..., "error": ...} 형태.
        """
        proc = self._procs.get(server_name)
        if proc is None:
            raise RuntimeError(f"서버 '{server_name}'이 기동되지 않았거나 종료됨")
        if proc.poll() is not None:
            raise RuntimeError(f"서버 '{server_name}'이 이미 종료됨")

        params: Dict[str, Any] = {"name": tool_name}
        if arguments is not None:
            params["arguments"] = arguments

        resp = self._send_jsonrpc(proc, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": params,
        }, timeout=30.0)

        if resp is None:
            return {"ok": False, "error": "서버 응답 없음 (EOF)"}
        if "error" in resp:
            return {"ok": False, "error": resp["error"]}
        if "result" not in resp:
            return {"ok": False, "error": "응답에 result 없음"}
        return {"ok": True, "result": resp["result"]}

    # ── 내부: JSON-RPC 통신 ────────────────────────────────────────────────────

    def _send_jsonrpc(self, proc: subprocess.Popen, request: Dict[str, Any], timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        """서버 프로세스에 JSON-RPC 요청을 보내고 응답을 받음."""
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
            except json.JSONDecodeError:
                continue
        raise RuntimeError(f"서버 응답 타임아웃 ({timeout}초)")

    # ── 상태 ────────────────────────────────────────────────────────────────────

    def list_servers(self) -> List[Dict[str, Any]]:
        """현재 기동 중인 서버 상태 목록."""
        result: List[Dict[str, Any]] = []
        for name, proc in self._procs.items():
            result.append({
                "name": name,
                "running": proc.poll() is None,
                "returncode": proc.returncode,
            })
        return result


# ── 편의 함수 (모듈 레벨) ────────────────────────────────────────────────────────

_default_host: Optional[MCPHost] = None


def start_all(config: Optional[Dict[str, Any]] = None) -> MCPHost:
    """기본 호스트를 생성·기동하고 반환."""
    global _default_host
    _default_host = MCPHost(config)
    _default_host.start_all()
    return _default_host


def list_all_tools() -> List[Dict[str, Any]]:
    """기본 호스트의 전체 도구 목록 반환."""
    if _default_host is None:
        raise RuntimeError("호스트가 시작되지 않음. start_all()을 먼저 호출하세요.")
    return _default_host.list_all_tools()


def call(server: str, tool: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """기본 호스트의 특정 도구 호출."""
    if _default_host is None:
        raise RuntimeError("호스트가 시작되지 않음. start_all()을 먼저 호출하세요.")
    return _default_host.call(server, tool, args)


def stop_all() -> List[str]:
    """기본 호스트의 모든 서버 종료."""
    if _default_host is None:
        return []
    return _default_host.stop_all()


# ── CLI (디버깅용) ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MCP stdio 서버 호스트 (디버깅용)")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH, help="mcpServers.json 경로")
    parser.add_argument("--list", action="store_true", help="도구 목록 출력 후 종료")
    parser.add_argument("--call", nargs=2, metavar=("SERVER", "TOOL"), help="서버.도구 호출")
    parser.add_argument("--call-args", type=json.loads, default=None, help="호출 인자 (JSON 문자열)")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
        host = MCPHost(config)
        print(f"[MCP Host] 설정 로딩 완료: {len(list_enabled_servers(config))}개 서버 (enabled)")
        started = host.start_all()
        print(f"[MCP Host] 기동: started={started['started']}, failed={started['failed']}")

        if args.list:
            tools = host.list_all_tools()
            print(f"\n[도구 목록] 총 {len(tools)}개:")
            for t in tools:
                print(f"  [{t['server']}] {t['name']}")

        if args.call:
            server_name, tool_name = args.call
            call_args = args.call_args or {}
            print(f"\n[호출] {server_name}.{tool_name}({json.dumps(call_args, ensure_ascii=False)})")
            resp = host.call(server_name, tool_name, call_args)
            print(json.dumps(resp, ensure_ascii=False, indent=2))

        host.stop_all()
        print("\n[MCP Host] 모든 서버 종료 완료")
    except Exception as exc:
        print(f"[MCP Host] 오류: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
