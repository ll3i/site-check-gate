"""
YOLO 객체 검출 래퍼 — 판정 없이 검출만 수행.

사용법:
    from service.core.photo_detect import detect_objects
    results = detect_objects("assets/vision/demo_photos/R1_L2_A동_1층_하역장.jpg", "defect")

반환:
    [
        {"label": "bolt", "conf": 0.82, "box": [x1, y1, x2, y2]},
        ...
    ]

domain은 반드시 지정해야 한다. 미지정 시 오류 발생 (교차 오탐 실측 이력 근거).
"""

from typing import List, Dict, Any

# ---------------------------------------------------------------------------
# 지연 임포트: ultralytics가 설치되지 않아도 이 섹션(Service)은 동작해야 하므로
# 실제 YOLO 호출 시점에 임포트한다.
# ---------------------------------------------------------------------------
def _import_yolo() -> Any:
    try:
        from ultralytics import YOLO
        return YOLO
    except ImportError as exc:
        raise ImportError(
            "비전 모듈(ultralytics)이 설치되지 않았습니다. "
            "서비스 코어 섹션은 이 의존성 없이도 동작하도록 설계되어 있으며, "
            "YOLO 검출이 필요한 경우에만 `pip install ultralytics`를 실행하세요. "
            "원본 예외: " + str(exc)
        ) from exc


# ---------------------------------------------------------------------------
# 허용된 domain 목록 — 여기에 없는 domain이 들어오면 오류 (의도적 교차 실행 방지)
# ---------------------------------------------------------------------------
ALLOWED_DOMAINS = frozenset({"defect", "gauge", "cleaning"})
WEIGHTS_DIR = "assets/vision/weights"


# ---------------------------------------------------------------------------
# 객체 검출 (판정 없음 — 검출 결과만 반환)
# ---------------------------------------------------------------------------
def detect_objects(image_path: str, domain: str) -> List[Dict[str, Any]]:
    """YOLO 검출 래퍼.

    Args:
        image_path: 추론할 이미지 파일 경로.
        domain: 사용할 가중치 도메인 ('defect' | 'gauge' | 'cleaning').
                미지정(None/빈 문자열)이거나 허용되지 않은 도메인이면 ValueError를
                발생시킨다. 전 도메인 동시 실행은 교차 오탐 실측 이력에 근거해
                금지되어 있다.

    Returns:
        리스트 of dict, 각 dict는 다음 키를 가진다:
            - label (str): 예측 클래스명
            - conf (float): 신뢰도 (0~1)
            - box (list[int]): [x1, y1, x2, y2] (픽셀 좌표)

    Raises:
        ValueError: domain이 미지정이거나 허용되지 않은 경우.
        ImportError: ultralytics가 설치되지 않은 경우.
        FileNotFoundError: 가중치 파일 또는 이미지 파일이 없는 경우.
    """
    # --- domain 검증 ----------------------------------------------------------
    # 공백 제거만 수행: 대소문자/공백 유연 매칭은 하지 않고
    # 허용된 소문자 도메인('defect','gauge','cleaning')과 정확히 일치시킨다.
    # 이는 교차 오탐 실측 이력에 근거한 엄격한 검증이다.
    if not isinstance(domain, str):
        raise ValueError(
            "domain은 문자열이어야 합니다. 'defect', 'gauge', 'cleaning' 중 하나를 "
            "명시적으로 지정하세요. 전 도메인 동시 실행은 교차 오탐 실측 이력에 따라 "
            "금지되어 있습니다."
        )

    domain = domain.strip()
    if not domain:
        raise ValueError(
            "domain 인자가 필요합니다. 'defect', 'gauge', 'cleaning' 중 하나를 "
            "명시적으로 지정하세요. 전 도메인 동시 실행은 교차 오탐 실측 이력에 따라 "
            "금지되어 있습니다."
        )

    if domain not in ALLOWED_DOMAINS:
        raise ValueError(
            f"알 수 없는 domain: '{domain}'. "
            f"허용 도메인: {sorted(ALLOWED_DOMAINS)}. "
            f"미지정 또는 교차 실행은 금지됩니다."
        )

    # --- 경로 조립 -------------------------------------------------------------
    weight_path = f"{WEIGHTS_DIR}/{domain}.pt"
    import os
    if not os.path.isfile(weight_path):
        raise FileNotFoundError(f"가중치 파일을 찾을 수 없습니다: {weight_path}")

    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"이미지 파일을 찾을 수 없습니다: {image_path}")

    # --- 지연 임포트 -----------------------------------------------------------
    YOLO = _import_yolo()

    # --- 추론 ------------------------------------------------------------------
    model = YOLO(weight_path)
    conf_threshold = 0.25

    # predict() 결과로 리스트로 변환
    results = model.predict(
        source=image_path,
        conf=conf_threshold,
        device="cpu",
        verbose=False,
    )

    detections: List[Dict[str, Any]] = []
    for result in results:
        boxes = result.boxes
        if boxes is None:
            continue

        for box in boxes:
            # conf가 임계값 미만이면 이미 걸러졌지만 안전망
            conf_val = float(box.conf)
            if conf_val < conf_threshold:
                continue

            cls_idx = int(box.cls.item()) if hasattr(box.cls, "item") else int(box.cls)
            x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
            detections.append(
                {
                    "label": model.names.get(cls_idx, str(cls_idx)),
                    "conf": round(conf_val, 4),
                    "box": [x1, y1, x2, y2],
                }
            )

    return detections
