#!/usr/bin/env python3
"""
subcontract_check.py — 고용노동부 「근로자파견의 판단기준에 관한 지침」의
판단 요소를 5축·약 20개 세부 점검항목으로 코드화하고,
문서 텍스트에서 각 항목의 근거 문장 후보를 키워드·패턴으로 찾아
[근거 있음-적법 방향 / 근거 있음-위험 신호 / 근거 없음-확인 필요] 3분기로 판정.

근거 문장 없이 판정하지 않는다.
"""

import re
from typing import Any, Dict, List, Optional, Pattern, Tuple

# ── 5축 데이터 정의 ────────────────────────────────────────────────────────────
#
# 각 축은 여러 세부 점검항목으로 구성되며,
# 세부 항목마다 "탐색 패턴"과 "적법 방향 키워드"/"위험 신호 키워드"를 둔다.
#
# 판정 원리:
#   문서에서 근거 문장 후보가 추출되고,
#   해당 문장들에 위험 신호 키워드가 하나라도 있으면 → "근거 있음-위험 신호"
#   근거 문장 후보만 있고 적법 방향 키워드가 있으면 → "근거 있음-적법 방향"
#   근거 문장 후보가 없으면 → "근거 없음-확인 필요"
#
# 근거 문장 후보: 항목과 연결된 키워드/패턴이 문서 텍스트에 등장한 문장.

# 조문 단위: (축 번호, 항목 번호, 항목명, 설명, 탐색 패턴 리스트,
#              적법 방향 키워드 리스트, 위험 신호 키워드 리스트)

# 탐색 패턴은 하나의 정규식으로, 문서에서 "근거 문장(문장 단위)"을 찾을 때
# 문장에 해당 패턴이 포함되는지 검사한다. 키워드는 단순 문자열 포함 검사.

# 판정 라벨 (3분기)
LABEL_FOUND_COMPLIANT = "근거 있음-적법 방향"
LABEL_FOUND_RISK = "근거 있음-위험 신호"
LABEL_NONEED = "근거 없음-확인 필요"


# ── 항목 데이터 ────────────────────────────────────────────────────────────────

# 형식:
#   {
#       "axis": int,
#       "item": int,
#       "name": str,
#       "desc": str,
#       "patterns": [컴파일된 re.Pattern, ...],    # 근거 문장 탐색용
#       "compliant_keywords": [str, ...],          # 적법 방향 신호
#       "risk_keywords": [str, ...],                # 위험 신호
#   }
#
# 패턴 리스트는 "문장에 이 패턴이 하나라도 있으면 근거 문장 후보"로 취급한다.
# 항목 특성상 "없음"을 근거로 삼을 수 없으므로, 패턴이 아예 매칭되지 않으면
# 근거 없음-확인 필요.

SUBSECTION_ITEMS: List[Dict[str, Any]] = [
    # ── 축 1: 업무 수행상 상당한 지휘·명령 여부 ───────────────────────────────
    {
        "axis": 1,
        "item": 1,
        "name": "작업 지시·명령의 원청 직접성",
        "desc": "원청(도급인)이 수급인 근로자에게 직접 작업 지시를 하는가.",
        "patterns": [
            re.compile(r"직접\s*(지시|명령|작업\s*지시|업무\s*지시)", re.IGNORECASE),
            re.compile(r"원청\s*(직원|관리자|담당자)\s*(지시|명령|말씀|요구)", re.IGNORECASE),
            re.compile(r"파견\s*근로자\s*(지시|명령)", re.IGNORECASE),
        ],
        "compliant_keywords": [
            "수급인 지휘",
            "수급인이 지시",
            "소속 현장관리자",
            "수급인 측 지시",
            "도급사 지시",
        ],
        "risk_keywords": [
            "원청이 직접 지시",
            "원청 직원 지시",
            "직접 작업 지시",
            "원청 담당자가 지시",
            "원청의 구체적인 지시",
        ],
    },
    {
        "axis": 1,
        "item": 2,
        "name": "작업 방법·순서·공정의 원청 관여",
        "desc": "작업 방법, 순서, 공정 수행에 원청이 구체적 지시를 하는가.",
        "patterns": [
            re.compile(r"작업\s*방법|작업\s*순서|공정\s*수행|작업\s*순서\s*결정", re.IGNORECASE),
            re.compile(r"구체적\s*(지시|방법|절차)", re.IGNORECASE),
        ],
        "compliant_keywords": [
            "수급인 책임 하 작업방법",
            "수급인이 공정 관리",
            "도급 계약에 따른 방식",
        ],
        "risk_keywords": [
            "원청이 작업 방법 지정",
            "원청이 공정 지휘",
            "원청 지시에 따라 작업 방법",
            "원청이 구체적 작업 방식 지시",
        ],
    },
    {
        "axis": 1,
        "item": 3,
        "name": "원청의 근태·근무시간 통제",
        "desc": "원청이 출퇴근, 휴게, 근무시간을 직접 통제하는가.",
        "patterns": [
            re.compile(r"출퇴근|근무\s*시간|휴게|근태|출근|퇴근|지각|조퇴", re.IGNORECASE),
            re.compile(r"원청\s*(통제|관리|확인|승인)", re.IGNORECASE),
        ],
        "compliant_keywords": [
            "수급인이 근태 관리",
            "수급인 소속 관리자",
            "수급인이 출퇴근 관리",
        ],
        "risk_keywords": [
            "원청이 근태 확인",
            "원청이 출퇴근 통제",
            "원청이 근무시간 직접 관리",
            "원청 승인 후 퇴근",
        ],
    },
    {
        "axis": 1,
        "item": 4,
        "name": "원청의 징계·주의·시정 지시",
        "desc": "작업 태도·절차에 대한 징계·주의를 원청이 직접 하는가.",
        "patterns": [
            re.compile(r"징계|주의|시정\s*요구|불이익|경고|문책|징계\s*절차", re.IGNORECASE),
            re.compile(r"원청\s*(징계|주의|경고|시정)", re.IGNORECASE),
        ],
        "compliant_keywords": [
            "수급인이 징계",
            "수급인 내부 징계",
            "도급 계약 상 책임",
        ],
        "risk_keywords": [
            "원청이 징계",
            "원청이 직접 주의",
            "원청이 시정 요구",
            "원청이 불이익 조치",
        ],
    },

    # ── 축 2: 도급인 사업에의 실질적 편입 ───────────────────────────────────────
    {
        "axis": 2,
        "item": 1,
        "name": "혼재 작업·동일 장소 공동 작업 여부",
        "desc": "수급인 근로자가 원청 근로자와 같은 장소·라인에서 혼재되어 작업하는가.",
        "patterns": [
            re.compile(r"혼재|공동\s*작업|같은\s*장소|동일\s*라인|한\s*공간| 혼재 ", re.IGNORECASE),
            re.compile(r"원청\s*근로자와\s*(함께|동일|혼재)", re.IGNORECASE),
        ],
        "compliant_keywords": [
            "분리된 작업 공간",
            "독립된 작업 구역",
            "별도 장소",
        ],
        "risk_keywords": [
            "원청 근로자와 혼재",
            "원청 직원과 같은 장소",
            "공동 작업 라인",
            "원청 라인에서 함께 작업",
        ],
    },
    {
        "axis": 2,
        "item": 2,
        "name": "원청 업무 프로세스·조회·보고 체계 편입",
        "desc": "수급인 근로자가 원청의 조회, 보고 체계, 회의에 직접 참여하는가.",
        "patterns": [
            re.compile(r"조회|아침\s*조회|업무\s*보고|회의\s*참석|원청\s*회의|보고\s*체계", re.IGNORECASE),
            re.compile(r"원청\s*(조회|보고|회의|이메일|시스템)", re.IGNORECASE),
        ],
        "compliant_keywords": [
            "수급인에게 별도 보고",
            "수급인 경유 보고",
            "도급사 경유",
        ],
        "risk_keywords": [
            "원청 조회에 직접 참석",
            "원청에 직접 보고",
            "원청 회의에 참여",
            "원청 시스템으로 직접 입력",
        ],
    },
    {
        "axis": 2,
        "item": 3,
        "name": "원청 조직·코드·계정·자산 사용 여부",
        "desc": "수급인 근로자가 원청의 조직 코드, 사내 계정, 자산(명찰·시스템 등)을 사용하는가.",
        "patterns": [
            re.compile(r"사내\s*(계정|시스템|이메일|그룹웨어| intranet|인트라넷)", re.IGNORECASE),
            re.compile(r"원청\s*(명찰|사번|출입증|계정|권한)", re.IGNORECASE),
        ],
        "compliant_keywords": [
            "수급인 자체 계정",
            "수급인 명의",
            "도급사 별도 시스템",
        ],
        "risk_keywords": [
            "원청 사내 계정 사용",
            "원청 이메일로 업무",
            "원청 시스템 직접 로그인",
            "원청 명찰 착용",
        ],
    },

    # ── 축 3: 인사·노무 결정권 소재 ─────────────────────────────────────────────
    {
        "axis": 3,
        "item": 1,
        "name": "채용·선발 권한 소재",
        "desc": "근로자 채용·선발이 원청에 의해 이루어지거나 원청의 승인을 받는가.",
        "patterns": [
            re.compile(r"채용|선발|면접|서류\s*전형|합격|입사|계약\s*체결", re.IGNORECASE),
            re.compile(r"원청\s*(채용|선발|승인|면접|합격)", re.IGNORECASE),
        ],
        "compliant_keywords": [
            "수급인이 채용",
            "수급인 선발",
            "도급사에서 입사",
            "수급인 소속 채용",
        ],
        "risk_keywords": [
            "원청이 채용 결정",
            "원청이 면접",
            "원청 승인 후 입사",
            "원청이 선발",
        ],
    },
    {
        "axis": 3,
        "item": 2,
        "name": "배치·작업 배치 전환 권한 소재",
        "desc": "작업 현장 배치, 조 편성, 작업 전환이 원청에 의해 결정되는가.",
        "patterns": [
            re.compile(r"배치|작업\s*배정|조\s*편성|인력\s*배치|전환|현장\s*배치", re.IGNORECASE),
            re.compile(r"원청\s*(배치|배정|전환|편성)", re.IGNORECASE),
        ],
        "compliant_keywords": [
            "수급인이 배치",
            "수급인 관리자와 협의",
            "도급 계약 범위 내 배치",
        ],
        "risk_keywords": [
            "원청이 배치 결정",
            "원청이 작업 배정",
            "원청이 조 편성",
            "원청이 인력 배치",
        ],
    },
    {
        "axis": 3,
        "item": 3,
        "name": "임금·수당·처우 결정권 소재",
        "desc": "임금, 수당, 처우 조건이 원청에 의해 직접 결정되는가.",
        "patterns": [
            re.compile(r"임금|급여|수당|처우|급여\s*수준|시급|월급|임금\s*지급", re.IGNORECASE),
            re.compile(r"원청\s*(임금|급여|수당|처우|시급)", re.IGNORECASE),
        ],
        "compliant_keywords": [
            "수급인이 임금 지급",
            "수급인이 급여 결정",
            "도급 계약에 따른 임금",
        ],
        "risk_keywords": [
            "원청이 임금 직접 지급",
            "원청이 급여 결정",
            "원청이 수당 책정",
            "원청이 처우 결정",
        ],
    },
    {
        "axis": 3,
        "item": 4,
        "name": "징계·해고·인사 조치 권한 소재",
        "desc": "징계, 해고, 인사 조치가 원청에 의해 이루어지는가.",
        "patterns": [
            re.compile(r"징계|해고|인사\s*조치|면직|권고사직|계약\s*해지|인사\s*결정", re.IGNORECASE),
            re.compile(r"원청\s*(징계|해고|인사|계약\s*해지|면직)", re.IGNORECASE),
        ],
        "compliant_keywords": [
            "수급인이 징계",
            "수급인이 해고",
            "수급인 인사 결정",
            "도급사 내부 징계",
        ],
        "risk_keywords": [
            "원청이 징계",
            "원청이 해고",
            "원청이 인사 조치",
            "원청이 계약 해지",
        ],
    },

    # ── 축 4: 계약 목적의 확정성·전문성·기술성 ────────────────────────────────
    {
        "axis": 4,
        "item": 1,
        "name": "계약 목적·업무의 구체적 확정성",
        "desc": "도급 계약 목적이 특정 업무·결과물로 명확히 확정되어 있는가.",
        "patterns": [
            re.compile(r"도급\s*계약|계약\s*목적|업무\s*범위|과업\s*내용|계약\s*내역|수급\s*업무", re.IGNORECASE),
            re.compile(r"구체적\s*(업무|과업|목적물|결과물|작업\s*범위)", re.IGNORECASE),
        ],
        "compliant_keywords": [
            "특정 업무 위탁",
            "목적물 납품",
            "결과물 기준 계약",
            "과업 명확한 계약",
        ],
        "risk_keywords": [
            "포괄적 인력 공급",
            "단순 인력 파견",
            "원청 업무 전반 수행",
            "원청이 수시로 업무 지정",
        ],
    },
    {
        "axis": 4,
        "item": 2,
        "name": "전문 기술·특수 장비·독자적 노하우 요구",
        "desc": "위탁 업무가 전문 기술, 특수 장비, 독자적 노하우를 요구하는가.",
        "patterns": [
            re.compile(r"전문\s*기술|특수\s*장비|독자적\s*기술|노하우|전문\s*인력|특수\s*기능", re.IGNORECASE),
            re.compile(r"고도\s*기술|전문\s*장비|특수\s*공법|전문\s*소프트웨어", re.IGNORECASE),
        ],
        "compliant_keywords": [
            "전문 기술 인력 투입",
            "특수 장비 운용",
            "독자적 노하우 보유",
            "전문 업체 수행",
        ],
        "risk_keywords": [
            "단순 반복 업무",
            "비전문 인력",
            "누구나 수행 가능한 업무",
            "특별한 기술 없이 수행",
        ],
    },
    {
        "axis": 4,
        "item": 3,
        "name": "결과 중심 계약 vs 과정·인력 중심 계약",
        "desc": "계약이 결과(목적물) 기준인지, 아니면 인력 공급·작업 시간 기준인지.",
        "patterns": [
            re.compile(r"결과물|목적물|납품|성과|준공|완성|결과\s*기준", re.IGNORECASE),
            re.compile(r"인력\s*공급|인원\s*파견|작업\s*시간\s*기준|맨아워|맨파워|인력\s*파견", re.IGNORECASE),
        ],
        "compliant_keywords": [
            "결과물 기준 계약",
            "목적물 납품 계약",
            "성과 기준 계약",
            "도급 금액 결과 연동",
        ],
        "risk_keywords": [
            "인력 공급 계약",
            "맨아워 기준 계약",
            "인원 수 기준 계약",
            "작업 시간 기준 정산",
        ],
    },

    # ── 축 5: 수급인의 기업 실체 ──────────────────────────────────────────────
    {
        "axis": 5,
        "item": 1,
        "name": "수급인의 장비·공구·시설 보유",
        "desc": "수급인이 자기 장비·공구·시설을 보유하고 작업에 투입하는가.",
        "patterns": [
            re.compile(r"수급인\s*(장비|공구|시설|보유|투입)", re.IGNORECASE),
            re.compile(r"자제\s*(장비|공구|설비|시설|차량|기계)", re.IGNORECASE),
            re.compile(r"자체\s*장비|자체\s*시설|직접\s*보유\s*장비", re.IGNORECASE),
        ],
        "compliant_keywords": [
            "수급인 자체 장비",
            "수급인이 장비 투입",
            "자체 설비 보유",
            "도급사 장비 사용",
        ],
        "risk_keywords": [
            "원청 장비 사용",
            "원청 시설만 사용",
            "원청 제공 장비에만 의존",
            "장비 없이 원청 자산 사용",
        ],
    },
    {
        "axis": 5,
        "item": 2,
        "name": "수급인의 자금·사업 독립성",
        "desc": "수급인이 자기 자본과 사업체로 독립적으로 운영되는가.",
        "patterns": [
            re.compile(r"독립\s*법인|별도\s*사업체|수급인\s*사업|자체\s*사업|매출|자본금|사업체", re.IGNORECASE),
            re.compile(r"도급\s*사업|위탁\s*사업|전문\s*업체|수급\s*사업자", re.IGNORECASE),
        ],
        "compliant_keywords": [
            "별도 법인",
            "독립 사업자",
            "자체 사업체 보유",
            "전문 도급 업체",
        ],
        "risk_keywords": [
            "원청의 하부 조직",
            "독립성 없는 사업체",
            "형식상 업체",
            "페이퍼 컴퍼니",
            "실체 없는 업체",
        ],
    },
    {
        "axis": 5,
        "item": 3,
        "name": "수급인의 법적 책임 소재",
        "desc": "안전·품질·법적 책임이 수급인에게 귀속되는가.",
        "patterns": [
            re.compile(r"책임|법적\s*책임|안전\s*책임|품질\s*책임|민형사상\s*책임|책임\s*소재", re.IGNORECASE),
            re.compile(r"수급인\s*책임|도급사\s*책임|계약\s*상\s*책임", re.IGNORECASE),
        ],
        "compliant_keywords": [
            "수급인이 안전 책임",
            "수급인이 품질 책임",
            "계약 상 수급인 책임",
            "수급인 명의로 책임",
        ],
        "risk_keywords": [
            "원청이 직접 책임 부담",
            "책임 전가 없이 원청 책임",
            "실질 책임 원청",
            "원청이 모든 책임 부담",
        ],
    },
    {
        "axis": 5,
        "item": 4,
        "name": "수급인의 사업주로서 조직·관리 체계",
        "desc": "수급인이 사업주로서 현장 관리자, 조직 체계, 관리 규정을 갖추고 있는가.",
        "patterns": [
            re.compile(r"현장\s*관리자|관리\s*체계|관리\s*규정|조직\s*체계|관리직|감독자", re.IGNORECASE),
            re.compile(r"수급인\s*(관리자|조직|관리|책임자|소속)", re.IGNORECASE),
        ],
        "compliant_keywords": [
            "수급인 소속 관리자",
            "수급인 조직 체계",
            "관리 규정 보유",
            "자체 관리 체계",
        ],
        "risk_keywords": [
            "원청 관리자만 존재",
            "수급인 관리자 부재",
            "관리 체계 없음",
            "원청이 실질 관리",
        ],
    },
]


# ── 탐색·판정 엔진 ────────────────────────────────────────────────────────────

def _split_sentences(text: str) -> List[str]:
    """
    문서 텍스트를 문장 단위로 분할.
    문장 경계: 。/./?!/?/;:/newline + 한국어-ish 경계.
    빈 문장 제거.
    """
    # 여러 문장 구분자를 하나의 구분에 가깝게 처리
    parts = re.split(r"[\.\?！！；;:\n]+", text)
    return [p.strip() for p in parts if p.strip()]


def _sentence_matches_patterns(sentence: str, patterns: List[Pattern]) -> bool:
    """문장에 패턴 중 하나라도 매칭되면 True."""
    for p in patterns:
        if p.search(sentence):
            return True
    return False


def _sentence_has_keyword(sentence: str, keywords: List[str]) -> bool:
    """문장에 키워드 중 하나라도 포함되면 True (부분 문자열 포함)."""
    for kw in keywords:
        if kw in sentence:
            return True
    return False


def _negation_in_sentence(sentence: str) -> bool:
    """문장에 부정(negation) 단서가 있으면 True.
    '근태 관련 내용은 없다'처럼 패턴이Hit해도 실제 근거가 아닌 문장을 거른다.
    """
    negators = [
        "없다", "없는", "아니", "않", "없음", "아니어",
        "나오지", "언급되지", "기재되지", "확인되지",
    ]
    s = sentence.lower()
    return any(neg in s for neg in negators)


def evaluate_item(
    item: Dict[str, Any],
    text: str,
) -> Dict[str, Any]:
    """
    단일 세부 점검항목을 문서 텍스트에 대해 평가.

    반환:
        {
            "axis": int,
            "item": int,
            "name": str,
            "desc": str,
            "label": 판정 라벨 (3분기),
            "evidence_sentences": 근거 문장 후보 리스트 (있을 경우),
            "matched_patterns": 매칭된 패턴 문자열 표현 (디버깅용),
            "compliant_keywords_hit": 적법 방향 키워드 중 매칭된 것,
            "risk_keywords_hit": 위험 신호 키워드 중 매칭된 것,
        }
    """
    sentences = _split_sentences(text)
    patterns = item["patterns"]
    compliant_kw = item["compliant_keywords"]
    risk_kw = item["risk_keywords"]

    evidence: List[str] = []
    matched_patterns: List[str] = []
    compliant_hits: List[str] = []
    risk_hits: List[str] = []

    for s in sentences:
        if _sentence_matches_patterns(s, patterns):
            # 부정 단서가 있으면 근거 문장으로 간주하지 않는다
            if _negation_in_sentence(s):
                continue
            evidence.append(s)
            for p in patterns:
                if p.search(s):
                    desc = p.pattern[:60]
                    if desc not in matched_patterns:
                        matched_patterns.append(desc)
            if _sentence_has_keyword(s, risk_kw):
                for kw in risk_kw:
                    if kw in s and kw not in risk_hits:
                        risk_hits.append(kw)
            if _sentence_has_keyword(s, compliant_kw):
                for kw in compliant_kw:
                    if kw in s and kw not in compliant_hits:
                        compliant_hits.append(kw)

    if not evidence:
        return {
            "axis": item["axis"],
            "item": item["item"],
            "name": item["name"],
            "desc": item["desc"],
            "label": LABEL_NONEED,
            "evidence_sentences": [],
            "matched_patterns": [],
            "compliant_keywords_hit": [],
            "risk_keywords_hit": [],
        }

    if risk_hits:
        return {
            "axis": item["axis"],
            "item": item["item"],
            "name": item["name"],
            "desc": item["desc"],
            "label": LABEL_FOUND_RISK,
            "evidence_sentences": evidence,
            "matched_patterns": matched_patterns,
            "compliant_keywords_hit": compliant_hits,
            "risk_keywords_hit": risk_hits,
        }

    if compliant_hits:
        return {
            "axis": item["axis"],
            "item": item["item"],
            "name": item["name"],
            "desc": item["desc"],
            "label": LABEL_FOUND_COMPLIANT,
            "evidence_sentences": evidence,
            "matched_patterns": matched_patterns,
            "compliant_keywords_hit": compliant_hits,
            "risk_keywords_hit": [],
        }

    return {
        "axis": item["axis"],
        "item": item["item"],
        "name": item["name"],
        "desc": item["desc"],
        "label": LABEL_FOUND_COMPLIANT,
        "evidence_sentences": evidence,
        "matched_patterns": matched_patterns,
        "compliant_keywords_hit": [],
        "risk_keywords_hit": [],
    }


def check_subcontract(text: str) -> Dict[str, Any]:
    """
    문서 텍스트에 대해 적법도급 체크리스트 전 항목 평가.

    반환:
        {
            "total_items": 전체 항목 수,
            "results": [evaluate_item 결과 dict, ...]  (축 순, 항목 순 정렬),
            "axis_summary": {
                축 번호: {
                    "item_count": 항목 수,
                    "risk_count": 위험 신호 항목 수,
                    "compliant_count": 적법 방향 항목 수,
                    "noneed_count": 근거 없음 항목 수,
                }
            },
            "text_length": 원문 길이,
        }
    """
    results = [evaluate_item(item, text) for item in SUBSECTION_ITEMS]
    # 이미 SUBSECTION_ITEMS가 축→항목 순이므로 그대로 사용
    axis_summary: Dict[int, Dict[str, int]] = {}
    for r in results:
        ax = r["axis"]
        if ax not in axis_summary:
            axis_summary[ax] = {"item_count": 0, "risk_count": 0, "compliant_count": 0, "noneed_count": 0}
        axis_summary[ax]["item_count"] += 1
        label = r["label"]
        if label == LABEL_FOUND_RISK:
            axis_summary[ax]["risk_count"] += 1
        elif label == LABEL_FOUND_COMPLIANT:
            axis_summary[ax]["compliant_count"] += 1
        elif label == LABEL_NONEED:
            axis_summary[ax]["noneed_count"] += 1

    return {
        "total_items": len(results),
        "results": results,
        "axis_summary": axis_summary,
        "text_length": len(text),
    }


def check_subcontract_json(text: str) -> str:
    """check_subcontract 결과의 JSON 문자열."""
    import json
    return json.dumps(check_subcontract(text), ensure_ascii=False, indent=2)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from pathlib import Path

    text = ""
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        text = p.read_text(encoding="utf-8")
    else:
        print("사용법: python subcontract_check.py <텍스트파일>", file=sys.stderr)
        sys.exit(1)

    out = check_subcontract(text)
    print(json.dumps(out, ensure_ascii=False, indent=2))
