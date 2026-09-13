#!/usr/bin/env python3
"""
tests/test_host.py — MCP 호스트 통합 테스트.

1) mcpServers.json 의 enabled:true 서버 전부를 기동 (start_all)
2) tools/list 합계 도구 수를 확인 (10개 서버, 서버별 1~2개 → 예상 11개)
3) cite 계열이 아닌 가벼운 tool 1개(site_rules.check_subcontract) 왕복 확인
4) stop_all 로 정리
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

# 프로젝트 루트 확보
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from service.mcp_host import (
    MCPHost,
    load_config,
    list_enabled_servers,
    start_all,
    list_all_tools,
    call,
    stop_all,
)


# ── 상수 ─────────────────────────────────────────────────────────────────────────

CONFIG_PATH = PROJECT_ROOT / "mcpServers.json"

# site_rules.check_subcontract 테스트 입력
SAMPLE_SUBCONTRACT_TEXT = (
    "당사는 원청이 직접 작업 지시를 하고 있으며, "
    "원청 직원이 수급인 근로자에게 직접 작업 방법을 지시한다. "
    "또한 원청이 출퇴근 시간과 근무 시간을 직접 통제하며, "
    "원청 관리자가 수급인 근로자에 대한 징계를 직접 수행한다. "
    "원청 근로자와 같은 장소에서 혼재되어 작업하고 있으며, "
    "원청 시스템에 직접 로그인하여 업무를 처리한다."
)


# ── 헬퍼: 서버 개수 검증 ──────────────────────────────────────────────────────────

def _expected_enabled_count() -> int:
    """mcpServers.json 의 enabled:true 서버 개수."""
    cfg = load_config(CONFIG_PATH)
    servers = cfg.get("mcpServers", {})
    return sum(1 for s in servers.values() if isinstance(s, dict) and s.get("enabled", False))


# ── 테스트: 설정 로딩 ─────────────────────────────────────────────────────────────

def test_config_loads():
    """mcpServers.json 이 정상적으로 로딩되고 contest_brief 가 enabled:true 로 존재하는지 확인."""
    cfg = load_config(CONFIG_PATH)
    assert "mcpServers" in cfg
    servers = cfg["mcpServers"]

    # enabled 서버 개수 확인
    enabled_names = [
        name for name, spec in servers.items()
        if isinstance(spec, dict) and spec.get("enabled", False)
    ]
    assert len(enabled_names) == 11, f"enabled 서버 11개 기대, 실제 {len(enabled_names)}: {enabled_names}"

    # contest_brief 가 enabled:true 로 존재하는지 확인
    assert "contest_brief" in servers, "contest_brief 항목이 mcpServers.json 에 없음"
    cb = servers["contest_brief"]
    assert isinstance(cb, dict), "contest_brief 항목이 dict가 아님"
    assert cb.get("enabled") is True, "contest_brief 는 enabled:true 여야 함"


def test_enabled_server_names():
    """enabled 서버 이름 목록을 확인."""
    servers = list_enabled_servers(load_config(CONFIG_PATH))
    names = [s["name"] for s in servers]
    expected = {
        "cite_core", "pii_guard", "law_registry", "site_rules",
        "scholar_search", "retraction_check", "url_check", "wayback",
        "doc_parse", "photo_inspect", "contest_brief",
    }
    assert set(names) == expected, f"서버 목록 불일치: {names} vs {expected}"


# ── 테스트: 호스트 기동·정지 ──────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def host():
    """모듈 스코프 호스트: 모든 서버 기동 → 테스트 → 종료."""
    h = MCPHost(load_config(CONFIG_PATH))
    result = h.start_all(timeout_per_server=8.0)
    started = result["started"]
    failed = result["failed"]

    # 실패 서버가 있으면 테스트 전체 실패
    if failed:
        pytest.fail(f"서버 기동 실패: {failed}")

    # 기동 확인: enabled 서버 11개 (contest_brief 포함)
    assert len(started) == 11, f"11개 서버 기동 기대, 실제 {len(started)}: {started}"

    yield h

    # 정리
    h.stop_all()


def test_host_server_count(host: MCPHost):
    """기동된 서버 개수가 11개인지 확인 (contest_brief 포함)."""
    status = host.list_servers()
    running = [s for s in status if s["running"]]
    assert len(running) == 11, f"기동 중인 서버 11개 기대, 실제 {len(running)}"


# ── 테스트: tools/list 합계 ───────────────────────────────────────────────────────

def test_total_tools_count(host: MCPHost):
    """전체 tools/list 합계가 예상 범위 내인지 확인.

    # Server 도구 수: cite_core(2) + 나머지 9개 × 1 = 11개
    # 실제: cite_core(2), pii_guard(1), law_registry(2), site_rules(1),
    #       scholar_search(1), retraction_check(1), url_check(1), wayback(1),
    #       doc_parse(1), photo_inspect(1) = 12개? 확인 필요.
    # law_registry 가 2개(lookup_article, search_articles) 이므로 총 12개.
    """
    tools = host.list_all_tools()
    total = len(tools)

    # 서버별 도구 개수 출력 (디버깅용)
    by_server: dict[str, list[str]] = {}
    for t in tools:
        by_server.setdefault(t["server"], []).append(t["name"])

    print("\n[tools/list 집계]")
    for srv in sorted(by_server):
        print(f"  {srv}: {by_server[srv]}")
    print(f"  총 {total}개 도구")

    # cite_core가 2개(verify_references, match_claim), law_registry가 2개(lookup_article, search_articles)
    # 나머지 서버들은 각 1개씩 → 총 13개 예상 (contest_brief +1)
    assert total == 13, f"도구 13개 기대, 실제 {total}: {by_server}"

    # 서버별 도구 이름 확인
    assert by_server.get("site_rules") == ["check_subcontract"], f"site_rules 도구 불일치: {by_server.get('site_rules')}"
    assert by_server.get("photo_inspect") == ["detect_objects"], f"photo_inspect 도구 불일치: {by_server.get('photo_inspect')}"
    assert by_server.get("cite_core") == ["verify_references", "match_claim"], f"cite_core 도구 불일치"


# ── 테스트: cite 아닌 가벼운 tool 왕복 (site_rules.check_subcontract) ─────────────

def test_site_rules_check_subcontract(host: MCPHost):
    """cite 계열이 아닌 가벼운 tool 인 site_rules.check_subcontract 왕복 확인."""
    resp = host.call("site_rules", "check_subcontract", {"text": SAMPLE_SUBCONTRACT_TEXT})

    assert resp.get("ok") is True, f"tools/call 실패: {resp.get('error')}"

    # MCP 베이스가 핸들러 dict 결과를 content 블록의 텍스트로 직렬화하므로,
    # content[0].text 를 JSON 파싱하여 실제 결과를 추출한다.
    result_block = resp.get("result", {})
    assert isinstance(result_block, dict)

    content = result_block.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict) and first.get("type") == "text":
            text = first.get("text", "")
            result = json.loads(text)
        else:
            result = result_block
    else:
        result = result_block

    assert isinstance(result, dict)

    # check_subcontract 결과 구조 확인
    assert result.get("ok") is True, f"서버 내부 결과 ok=False: {result}"
    assert result.get("total_items", 0) > 0, "total_items 가 0"

    # 위험 신호가 있어야 함 (샘플 텍스트는 명백한 파견 정황)
    summary = result.get("summary", {})
    risk_count = summary.get("risk_count", 0)
    assert risk_count > 0, f"위험 신호가 0개 (예상: 1개 이상). summary={summary}"

    # has_risk_signal 플래그 확인
    assert result.get("has_risk_signal") is True, "has_risk_signal 이 True여야 함"

    # 축 요약 존재 확인
    axis_summary = result.get("axis_summary", {})
    assert len(axis_summary) > 0, "axis_summary 가 비어있음"

    print(f"\n[site_rules.check_subcontract 왕복 OK]")
    print(f"  총 항목: {result['total_items']}")
    print(f"  위험 신호: {risk_count}개")
    print(f"  축 요약: {json.dumps(axis_summary, ensure_ascii=False)}")
