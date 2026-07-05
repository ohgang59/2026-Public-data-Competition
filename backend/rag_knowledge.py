"""Sample RAG knowledge base for KTL TestMate demos.

These are intentionally marked as sample criteria. In production, replace or
extend SAMPLE_DOCUMENTS with official KTL submission guides, test-specific
checklists, FAQ, and supplement/rejection history.
"""
from __future__ import annotations

import re
from typing import Any

SAMPLE_DOCUMENTS: list[dict[str, Any]] = [
    {
        "id": "common-application-identity",
        "title": "공통 제출 기준: 신청자 및 사업자 식별",
        "tags": ["공통", "신청", "사업자", "연락처"],
        "text": "시험 신청서에는 회사명 또는 기관명, 사업자등록번호, 대표자명, 신청 담당자명, 전화번호, 이메일, 주소가 포함되어야 한다. 신청서의 회사명과 성적서 발급 대상 회사명이 다르면 담당자 확인 또는 보완 요청이 발생할 수 있다.",
        "check_items": [
            "회사명/기관명", "사업자등록번호", "대표자명", "신청 담당자", "연락처", "이메일", "주소"
        ],
    },
    {
        "id": "common-sample-identity",
        "title": "공통 제출 기준: 시료 식별 정보",
        "tags": ["공통", "시료", "모델", "제조사"],
        "text": "시료명, 품명, 모델명 또는 형식명, 제조사, 제조번호 또는 일련번호, 수량, 시료 상태를 명확히 기재해야 한다. 모델명 누락, 수량 불일치, 시료명과 첨부 문서의 제품명이 다른 경우 보완 위험이 높다.",
        "check_items": ["시료명", "품명", "모델명", "형식명", "제조사", "일련번호", "수량", "시료 상태"],
    },
    {
        "id": "common-test-scope",
        "title": "공통 제출 기준: 시험 범위와 규격",
        "tags": ["공통", "시험항목", "규격", "범위"],
        "text": "시험항목, 시험범위, 적용 규격 또는 기준, 요구 성능, 측정 조건, 성적서에 표기할 항목을 명확히 작성해야 한다. 시험항목이 포괄적으로만 적혀 있거나 규격 번호가 누락되면 담당자 확인이 필요하다.",
        "check_items": ["시험항목", "시험범위", "적용 규격", "기준", "측정 조건", "요구 성능"],
    },
    {
        "id": "common-report-issue",
        "title": "공통 제출 기준: 성적서 발급 옵션",
        "tags": ["공통", "성적서", "KOLAS", "국문", "영문"],
        "text": "성적서 종류, 국문/영문 여부, KOLAS 성적서 필요 여부, 발급 부수, 수령 방식, 납품 또는 제출 마감일을 명시해야 한다. KOLAS 여부가 불명확하면 발급 방식 확인으로 지연될 수 있다.",
        "check_items": ["성적서 종류", "국문", "영문", "KOLAS", "발급 부수", "수령 방식", "마감일"],
    },
    {
        "id": "common-return-payment",
        "title": "공통 제출 기준: 결제 및 시료 반환",
        "tags": ["공통", "결제", "반환", "세금계산서"],
        "text": "결제 방식, 세금계산서 발행 정보, 시료 반환 여부, 반환 주소, 택배 또는 방문 수령 여부를 기재하면 접수 후 반복 확인을 줄일 수 있다.",
        "check_items": ["결제 방식", "세금계산서", "반환 여부", "반환 주소", "택배", "방문 수령"],
    },
    {
        "id": "kolas-calibration-scope",
        "title": "KOLAS 교정 예시 기준: 교정 범위와 포인트",
        "tags": ["KOLAS", "교정", "측정범위", "불확도"],
        "text": "KOLAS 교정 신청은 교정 대상 장비명, 제조사, 모델명, 일련번호, 교정 범위, 교정 포인트, 분해능, 정확도, 희망 불확도 또는 허용오차 정보를 포함하는 것이 바람직하다. 교정 포인트가 없으면 담당자가 조건을 재확인해야 한다.",
        "check_items": ["장비명", "모델명", "일련번호", "교정 범위", "교정 포인트", "분해능", "정확도", "불확도"],
    },
    {
        "id": "electrical-safety-rating",
        "title": "전기·전자 시험 예시 기준: 정격 및 사용 조건",
        "tags": ["전기", "전자", "안전", "EMC", "정격"],
        "text": "전기·전자 또는 안전 시험은 정격 전압, 정격 전류, 주파수, 전원 방식, 소비전력, 사용 환경, 회로도 또는 제품 설명서가 필요할 수 있다. 정격 정보가 누락되면 시험 조건 설정이 지연된다.",
        "check_items": ["정격 전압", "정격 전류", "주파수", "전원 방식", "소비전력", "사용 환경", "회로도", "제품 설명서"],
    },
    {
        "id": "material-chemical-safety",
        "title": "화학·소재 시험 예시 기준: 재질 및 안전 정보",
        "tags": ["화학", "소재", "재료", "MSDS", "SDS"],
        "text": "화학·소재 관련 시험은 시료 재질, 성분, 함량, MSDS 또는 SDS, 보관 조건, 유해성 정보, 전처리 조건이 필요할 수 있다. 안전 정보가 없으면 시료 취급 가능 여부 확인이 필요하다.",
        "check_items": ["재질", "성분", "함량", "MSDS", "SDS", "보관 조건", "유해성", "전처리 조건"],
    },
    {
        "id": "schedule-deadline-risk",
        "title": "마감 일정 예시 기준: 납기 리스크",
        "tags": ["마감", "납기", "일정", "지연"],
        "text": "희망 완료일이 있는 경우 접수일, 예상 처리일, 보완 가능성, 휴일, 혼잡도를 함께 검토해야 한다. 마감 여유가 3영업일 미만이면 보완 요청 또는 혼잡 발생 시 납기 실패 위험이 높다.",
        "check_items": ["희망 완료일", "접수일", "마감 여유", "영업일", "혼잡도", "보완 가능성"],
    },
]


def _tokens(text: str) -> set[str]:
    raw = re.findall(r"[A-Za-z0-9가-힣]{2,}", (text or "").lower())
    return set(raw)


def retrieve(query: str, *, biz: str = "", mid: str = "", sub: str = "", top_k: int = 5) -> list[dict[str, Any]]:
    context = " ".join([query or "", biz or "", mid or "", sub or ""])
    q_tokens = _tokens(context)
    rows = []
    for doc in SAMPLE_DOCUMENTS:
        doc_text = " ".join([doc["title"], doc["text"], " ".join(doc.get("tags", [])), " ".join(doc.get("check_items", []))])
        d_tokens = _tokens(doc_text)
        overlap = len(q_tokens & d_tokens)
        tag_hit = sum(3 for tag in doc.get("tags", []) if tag.lower() in context.lower())
        item_hit = sum(2 for item in doc.get("check_items", []) if item.lower() in context.lower())
        score = overlap + tag_hit + item_hit
        if score > 0 or doc["id"].startswith("common"):
            item = dict(doc)
            item["score"] = score
            rows.append(item)
    rows.sort(key=lambda r: (-r["score"], r["id"]))
    return rows[:top_k]


def compact_sources(docs: list[dict[str, Any]]) -> str:
    parts = []
    for i, doc in enumerate(docs, 1):
        parts.append(
            f"[{i}] {doc['title']}\n"
            f"- id: {doc['id']}\n"
            f"- 기준: {doc['text']}\n"
            f"- 확인 항목: {', '.join(doc.get('check_items', []))}"
        )
    return "\n\n".join(parts)
