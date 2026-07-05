"""Decision-support layer for deadline success, document RAG checks,
and operations simulation.

The functions in this module are intentionally usable without an external LLM.
If OPENAI_API_KEY is added to .env later, the API reports that LLM enrichment is
available, but the deterministic checklist path remains the safe fallback for
contest demos and offline operation.
"""
from __future__ import annotations

import json
import math
import os
import re
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np

from . import ai_client
from .rag_knowledge import compact_sources, retrieve

from .predictor import ProcDaysPredictor, add_business_days
from .recommender import recommend

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"

COMMON_REQUIREMENTS = [
    {
        "id": "applicant_identity",
        "title": "신청자/사업자 정보",
        "required": True,
        "weight": 3,
        "keywords": ["회사명", "기관명", "사업자등록번호", "대표자", "신청자", "연락처", "전화", "이메일", "email"],
        "guidance": "회사명, 사업자등록번호, 담당자 연락처가 신청서와 일치하는지 확인하세요.",
    },
    {
        "id": "sample_identity",
        "title": "시료 식별 정보",
        "required": True,
        "weight": 3,
        "keywords": ["시료명", "품명", "모델", "형식", "제조사", "serial", "일련번호", "수량"],
        "guidance": "시료명, 모델명, 제조사, 수량이 빠지면 접수 후 보완 요청 가능성이 큽니다.",
    },
    {
        "id": "test_scope",
        "title": "시험 범위와 기준",
        "required": True,
        "weight": 4,
        "keywords": ["시험항목", "시험범위", "규격", "기준", "standard", "KOLAS", "성능", "측정", "교정"],
        "guidance": "어떤 항목을 어떤 기준으로 시험할지 명확해야 처리 지연을 줄일 수 있습니다.",
    },
    {
        "id": "report_options",
        "title": "성적서/발급 옵션",
        "required": True,
        "weight": 2,
        "keywords": ["성적서", "국문", "영문", "KOLAS", "발급", "원본", "사본", "납품"],
        "guidance": "성적서 종류와 언어, 발급 부수를 미리 확정하세요.",
    },
    {
        "id": "return_payment",
        "title": "결제 및 시료 반환 정보",
        "required": False,
        "weight": 1,
        "keywords": ["결제", "세금계산서", "반환", "택배", "방문", "주소", "수령"],
        "guidance": "결제 방식과 반환 주소가 있으면 후속 연락을 줄일 수 있습니다.",
    },
]

CATEGORY_REQUIREMENTS = [
    {
        "when": ["KOLAS", "교정"],
        "items": [
            {
                "id": "calibration_points",
                "title": "교정 포인트/범위",
                "required": True,
                "weight": 4,
                "keywords": ["교정점", "측정범위", "range", "point", "분해능", "정확도", "불확도"],
                "guidance": "교정점과 측정범위가 없으면 담당자가 시험 조건을 재확인해야 합니다.",
            }
        ],
    },
    {
        "when": ["전기", "전자", "안전", "EMC"],
        "items": [
            {
                "id": "electrical_rating",
                "title": "정격/전원 조건",
                "required": True,
                "weight": 3,
                "keywords": ["정격", "전압", "전류", "주파수", "전원", "AC", "DC", "Hz", "W"],
                "guidance": "정격과 전원 조건이 없으면 시험 세팅 확인으로 지연될 수 있습니다.",
            }
        ],
    },
    {
        "when": ["화학", "소재", "재료"],
        "items": [
            {
                "id": "material_safety",
                "title": "재질/안전 정보",
                "required": True,
                "weight": 3,
                "keywords": ["재질", "성분", "MSDS", "SDS", "위험", "보관", "유해", "함량"],
                "guidance": "재질과 안전 정보가 없으면 시료 취급 가능 여부 확인이 필요합니다.",
            }
        ],
    },
]


def _load_env() -> dict[str, str]:
    env = dict(os.environ)
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def llm_status() -> dict[str, Any]:
    return ai_client.public_status(False)


def business_days_between(start: date, end: date) -> int:
    if end <= start:
        return 0
    d = start
    n = 0
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def deadline_success(
    predictor: ProcDaysPredictor,
    *,
    biz: str,
    mid: str,
    sub: str,
    receive_on: date,
    deadline: date,
) -> dict[str, Any]:
    pred = predictor.predict(biz=biz, mid=mid, sub=sub, received_on=receive_on)
    target_days = business_days_between(receive_on, deadline)
    span = max(1.0, float(pred["high_days"]) - float(pred["low_days"]))
    sigma = max(1.5, span / 2.563, float(pred.get("history_std") or 0) * 0.35)
    z = (target_days - float(pred["predicted_days"])) / sigma
    probability = max(0.01, min(0.99, _norm_cdf(z)))
    slack_days = target_days - float(pred["predicted_days"])
    level = "safe" if probability >= 0.85 else "watch" if probability >= 0.65 else "risk" if probability >= 0.4 else "critical"
    label = {
        "safe": "안전",
        "watch": "주의",
        "risk": "위험",
        "critical": "매우 위험",
    }[level]
    latest_safe_receive = None
    for back in range(0, 45):
        candidate = receive_on - timedelta(days=back)
        if candidate.weekday() >= 5:
            continue
        check = predictor.predict(biz=biz, mid=mid, sub=sub, received_on=candidate)
        if date.fromisoformat(check["predicted_complete_at"]) <= deadline:
            latest_safe_receive = candidate.isoformat()
            break
    return {
        "prediction": pred,
        "deadline": deadline.isoformat(),
        "target_business_days": target_days,
        "slack_days": round(slack_days, 1),
        "success_probability": round(probability, 3),
        "success_percent": int(round(probability * 100)),
        "risk_level": level,
        "risk_label": label,
        "latest_safe_receive_on": latest_safe_receive,
    }


def risk_explanation(
    predictor: ProcDaysPredictor,
    *,
    biz: str,
    mid: str,
    sub: str,
    receive_on: date,
    deadline: Optional[date] = None,
) -> dict[str, Any]:
    pred = predictor.predict(biz=biz, mid=mid, sub=sub, received_on=receive_on)
    try:
        shap = predictor.explain(biz=biz, mid=mid, sub=sub, received_on=receive_on, top_k=5)
    except Exception:
        shap = {"top_features": []}

    causes: list[dict[str, Any]] = []
    std = float(pred.get("history_std") or 0)
    if std >= 14:
        causes.append({
            "type": "variance",
            "severity": "high" if std >= 25 else "medium",
            "message": f"같은 소분류의 과거 처리 편차가 큽니다(표준편차 {std:.1f}일).",
        })
    if pred.get("congestion") in ("높음", "매우 높음", "?믪쓬", "留ㅼ슦 ?믪쓬"):
        causes.append({
            "type": "congestion",
            "severity": "medium",
            "message": f"접수월 물량이 평균 대비 높은 구간입니다(월 {pred.get('monthly_volume')}건).",
        })
    if float(pred.get("confidence") or 1) < 0.7:
        causes.append({
            "type": "confidence",
            "severity": "medium",
            "message": "유사 사례 수 또는 처리 편차 때문에 예측 신뢰도가 낮습니다.",
        })
    if deadline:
        d = deadline_success(predictor, biz=biz, mid=mid, sub=sub, receive_on=receive_on, deadline=deadline)
        if d["slack_days"] < 3:
            causes.append({
                "type": "deadline",
                "severity": "high" if d["slack_days"] < 0 else "medium",
                "message": f"마감일까지 여유가 {d['slack_days']}영업일로 부족합니다(성공 확률 {d['success_percent']}%).",
            })
    for f in shap.get("top_features", [])[:3]:
        if float(f.get("shap") or 0) > 0:
            causes.append({
                "type": "model_factor",
                "severity": "low",
                "message": f"모델은 '{f.get('feature')}' 값이 처리기간을 늘리는 방향으로 작용한다고 판단했습니다.",
            })
    if not causes:
        causes.append({
            "type": "normal",
            "severity": "low",
            "message": "현재 조건에서는 뚜렷한 지연 신호가 크지 않습니다.",
        })
    high_count = sum(1 for c in causes if c["severity"] == "high")
    med_count = sum(1 for c in causes if c["severity"] == "medium")
    level = "high" if high_count else "medium" if med_count >= 2 else "low" if med_count == 0 else "watch"
    return {
        "prediction": pred,
        "risk_level": level,
        "risk_label": {"low": "낮음", "watch": "주의", "medium": "보통", "high": "높음"}[level],
        "causes": causes,
        "shap": shap,
    }


def _requirements_for(biz: str, mid: str, sub: str) -> list[dict[str, Any]]:
    ctx = " ".join([biz or "", mid or "", sub or ""])
    items = [dict(x) for x in COMMON_REQUIREMENTS]
    for rule in CATEGORY_REQUIREMENTS:
        if any(k.lower() in ctx.lower() for k in rule["when"]):
            items.extend(dict(x) for x in rule["items"])
    return items


def _extract_docx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            names = [n for n in zf.namelist() if n.startswith("word/") and n.endswith(".xml")]
            text = []
            for name in names:
                raw = zf.read(name).decode("utf-8", errors="ignore")
                raw = re.sub(r"<[^>]+>", " ", raw)
                text.append(raw)
            return "\n".join(text)
    except Exception:
        return ""


def _extract_pdf_like(data: bytes) -> str:
    raw = data.decode("latin-1", errors="ignore")
    chunks = re.findall(r"\(([^()]{0,2000})\)\s*Tj", raw)
    chunks += re.findall(r"\(([^()]{0,2000})\)", raw)
    cleaned = [c.replace("\\n", " ").replace("\\r", " ").replace("\\(", "(").replace("\\)", ")") for c in chunks]
    return " ".join(cleaned)


def extract_text(filename: str, data: bytes) -> dict[str, Any]:
    suffix = Path(filename or "").suffix.lower()
    text = ""
    if suffix == ".docx":
        text = _extract_docx(data)
    elif suffix == ".pdf":
        text = _extract_pdf_like(data)
    if not text:
        for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr", "latin-1"):
            try:
                text = data.decode(enc)
                break
            except Exception:
                continue
    text = re.sub(r"\s+", " ", text or "").strip()
    return {
        "filename": filename,
        "extension": suffix,
        "text": text[:20000],
        "text_length": len(text),
        "needs_ocr": suffix in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp") or len(text) < 40,
    }


def _keyword_hits(text: str, keywords: Iterable[str]) -> list[str]:
    low = text.lower()
    hits = []
    for kw in keywords:
        if kw.lower() in low:
            hits.append(kw)
    return hits


def _llm_review_document(
    *,
    extracted: dict[str, Any],
    fallback_result: dict[str, Any],
    rag_docs: list[dict[str, Any]],
    biz: str,
    mid: str,
    sub: str,
    notes: str,
) -> Optional[dict[str, Any]]:
    if not ai_client.settings()["enabled"]:
        return None
    doc_text = (extracted.get("text") or "")[:9000]
    sources = compact_sources(rag_docs)
    fallback_brief = json.dumps({
        "risk_score": fallback_result.get("risk_score"),
        "risk_label": fallback_result.get("risk_label"),
        "checklist": fallback_result.get("checklist", []),
    }, ensure_ascii=False)
    messages = [
        {
            "role": "system",
            "content": (
                "당신은 KTL TestMate의 RAG 기반 서류 사전점검 보조 AI입니다. "
                "당신은 최종 승인/반려를 결정하지 않습니다. 공식 심사관을 대체하지 말고, "
                "제공된 기준 문서와 업로드 문서 내용에 근거해 보완 위험과 확인 필요 항목만 판단하세요. "
                "반드시 JSON 객체만 반환하세요."
            ),
        },
        {
            "role": "user",
            "content": (
                f"[시험 분류]\n사업구분: {biz}\n중분류: {mid}\n소분류: {sub}\n\n"
                f"[사용자 메모]\n{notes or '-'}\n\n"
                f"[검색된 예시 기준 문서]\n{sources}\n\n"
                f"[로컬 1차 점검 결과]\n{fallback_brief}\n\n"
                f"[업로드 문서 발췌]\n{doc_text or '(텍스트 추출 부족)'}\n\n"
                "다음 스키마로 JSON을 반환하세요. "
                "risk_score는 0~100 정수, risk_level은 low/watch/medium/high 중 하나, "
                "risk_label은 낮음/주의/보통/높음 중 하나입니다. "
                "checklist는 4~8개 항목으로, 각 항목은 id,title,required,status,evidence,guidance를 포함하고 "
                "status는 ok/missing/review 중 하나입니다. "
                "summary는 한국어 2~3문장입니다. questions는 신청자에게 확인할 질문 목록입니다. "
                "caveat에는 '예시 기준 기반 사전점검이며 공식 판정이 아님' 취지를 포함하세요."
            ),
        },
    ]
    res = ai_client.chat_json(messages, temperature=0.1, max_tokens=1800)
    if not res.get("ok"):
        fallback_result["llm"] = res.get("status") or ai_client.public_status(False, res.get("error"))
        return None
    data = res.get("json") or {}
    try:
        risk_score = int(max(0, min(100, int(data.get("risk_score", fallback_result["risk_score"])))))
    except Exception:
        risk_score = int(fallback_result["risk_score"])
    level = str(data.get("risk_level") or fallback_result["risk_level"])
    if level not in {"low", "watch", "medium", "high"}:
        level = fallback_result["risk_level"]
    label = str(data.get("risk_label") or {"low": "낮음", "watch": "주의", "medium": "보통", "high": "높음"}[level])
    checklist = data.get("checklist") if isinstance(data.get("checklist"), list) else fallback_result.get("checklist", [])
    normalized = []
    for item in checklist[:10]:
        if not isinstance(item, dict):
            continue
        status = item.get("status") if item.get("status") in {"ok", "missing", "review"} else "review"
        evidence = item.get("evidence")
        hits = item.get("hits") if isinstance(item.get("hits"), list) else []
        if evidence and not hits:
            hits = [str(evidence)]
        normalized.append({
            "id": str(item.get("id") or "llm_check"),
            "title": str(item.get("title") or "확인 항목"),
            "required": bool(item.get("required", True)),
            "status": status,
            "hits": [str(x) for x in hits[:4]],
            "guidance": str(item.get("guidance") or "담당자 확인이 필요한 항목입니다."),
        })
    return {
        "risk_score": risk_score,
        "risk_level": level,
        "risk_label": label,
        "summary": str(data.get("summary") or fallback_result["summary"]),
        "checklist": normalized or fallback_result.get("checklist", []),
        "questions": data.get("questions") if isinstance(data.get("questions"), list) else [],
        "caveat": str(data.get("caveat") or "예시 기준 기반 사전점검이며 공식 판정이 아닙니다."),
        "llm": ai_client.public_status(True),
    }

def review_document(
    *,
    filename: str,
    data: bytes,
    biz: str,
    mid: str,
    sub: str,
    notes: str = "",
    form_context: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    extracted = extract_text(filename, data)
    ctx_text = " ".join([extracted["text"], notes or "", json.dumps(form_context or {}, ensure_ascii=False)])
    requirements = _requirements_for(biz, mid, sub)
    rag_docs = retrieve(ctx_text, biz=biz, mid=mid, sub=sub, top_k=6)
    checklist = []
    missing_weight = 0
    review_weight = 0
    total_weight = sum(int(r.get("weight", 1)) for r in requirements)
    for req in requirements:
        hits = _keyword_hits(ctx_text, req.get("keywords", []))
        status = "ok" if hits else "missing" if req.get("required") else "review"
        if status == "missing":
            missing_weight += int(req.get("weight", 1))
        elif status == "review":
            review_weight += int(req.get("weight", 1))
        checklist.append({
            "id": req["id"],
            "title": req["title"],
            "required": bool(req.get("required")),
            "status": status,
            "hits": hits[:6],
            "guidance": req["guidance"],
        })
    if extracted["needs_ocr"]:
        review_weight += 3
        checklist.append({
            "id": "ocr_needed",
            "title": "문서 텍스트 추출 한계",
            "required": False,
            "status": "review",
            "hits": [],
            "guidance": "스캔 이미지 또는 텍스트가 적은 파일입니다. OCR 또는 원본문서 제출이 필요할 수 있습니다.",
        })
    missing_ratio = missing_weight / max(total_weight, 1)
    risk_score = min(100, int(round(missing_ratio * 78 + review_weight * 4)))
    if risk_score >= 70:
        level, label = "high", "높음"
    elif risk_score >= 40:
        level, label = "medium", "보통"
    elif risk_score >= 20:
        level, label = "watch", "주의"
    else:
        level, label = "low", "낮음"
    delay_days = int(round(missing_weight * 0.9 + review_weight * 0.4))
    summary = [
        f"서류 보완/반려 위험도는 {label}입니다.",
        f"필수 항목 {sum(1 for c in checklist if c['required'])}개 중 {sum(1 for c in checklist if c['required'] and c['status'] == 'ok')}개가 문서에서 확인되었습니다.",
    ]
    if delay_days:
        summary.append(f"보완 요청이 발생하면 약 {delay_days}일의 추가 지연 가능성이 있습니다.")
    result = {
        "llm": llm_status(),
        "document": {k: v for k, v in extracted.items() if k != "text"},
        "risk_score": risk_score,
        "risk_level": level,
        "risk_label": label,
        "estimated_delay_days": delay_days,
        "summary": " ".join(summary),
        "checklist": checklist,
        "retrieved_requirements": [{"id": r["id"], "title": r["title"], "keywords": r["keywords"][:6]} for r in requirements],
        "rag_sources": [{"id": d["id"], "title": d["title"], "score": d.get("score", 0), "check_items": d.get("check_items", [])} for d in rag_docs],
        "caveat": "예시 기준 기반 사전점검이며 공식 판정이 아닙니다. 실제 도입 시 KTL 공식 기준서와 보완 이력으로 지식베이스를 교체해야 합니다.",
    }
    llm_review = _llm_review_document(extracted=extracted, fallback_result=result, rag_docs=rag_docs,
                                      biz=biz, mid=mid, sub=sub, notes=notes)
    if llm_review:
        result.update(llm_review)
        result["estimated_delay_days"] = max(result["estimated_delay_days"], int(round(result["risk_score"] / 20)))
    return result

def optimize_application_plan(
    predictor: ProcDaysPredictor,
    *,
    biz: str,
    mid: str,
    sub: str,
    earliest: date,
    latest: Optional[date],
    deadline: Optional[date],
    priority: str,
    n: int = 5,
    document_risk_score: int = 0,
) -> dict[str, Any]:
    recs = recommend(predictor, biz=biz, mid=mid, sub=sub, earliest=earliest, latest=latest, deadline=deadline, priority=priority, n=max(n, 5))
    enriched = []
    for r in recs:
        receive = date.fromisoformat(r["receive_on"])
        item = dict(r)
        if deadline:
            ds = deadline_success(predictor, biz=biz, mid=mid, sub=sub, receive_on=receive, deadline=deadline)
            adjusted = max(0.01, ds["success_probability"] - min(document_risk_score, 100) / 300.0)
            item["success_probability"] = round(adjusted, 3)
            item["success_percent"] = int(round(adjusted * 100))
            item["deadline_risk_label"] = ds["risk_label"]
            item["slack_days"] = ds["slack_days"]
        enriched.append(item)
    enriched.sort(key=lambda x: (x.get("success_probability", 0), x.get("score", 0)), reverse=True)
    best = enriched[0] if enriched else None
    actions = [
        "접수 전 시험 범위와 시료 식별 정보를 먼저 확정하세요.",
        "마감일이 중요하면 추천일 중 성공 확률이 가장 높은 날짜로 접수하세요.",
    ]
    if document_risk_score >= 40:
        actions.insert(0, "서류 보완 위험이 있어 접수 전 체크리스트 누락 항목을 보완하는 것이 우선입니다.")
    return {
        "best": best,
        "recommendations": enriched[:n],
        "actions": actions,
        "document_risk_score": document_risk_score,
        "llm": llm_status(),
    }


def ops_bottlenecks(predictor: ProcDaysPredictor, applications: list[Any], top_k: int = 10) -> dict[str, Any]:
    pending = [a for a in applications if getattr(a, "status", None) == "pending"]
    by_mid: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {"pending": 0, "predicted_sum": 0.0, "samples": []})
    for a in pending:
        key = (getattr(a, "biz", "") or "미분류", getattr(a, "category", "") or "미분류")
        by_mid[key]["pending"] += 1
        by_mid[key]["predicted_sum"] += float(getattr(a, "predicted_days", 0) or 0)
        if len(by_mid[key]["samples"]) < 3:
            by_mid[key]["samples"].append({"id": getattr(a, "id", None), "sample": getattr(a, "sample_name", None)})
    rows = []
    for (biz, mid), data in by_mid.items():
        avg_pred = data["predicted_sum"] / max(data["pending"], 1)
        hist = predictor.mid_stats[(predictor.mid_stats.iloc[:, 0].astype(str) == str(biz)) & (predictor.mid_stats.iloc[:, 1].astype(str) == str(mid))]
        hist_std = float(hist.iloc[0].get("std") or 0) if len(hist) else 7.0
        score = data["pending"] * 4 + avg_pred * 0.8 + hist_std * 0.5
        rows.append({
            "biz": biz,
            "mid": mid,
            "pending": data["pending"],
            "avg_predicted_days": round(avg_pred, 1),
            "history_std": round(hist_std, 1),
            "score": round(score, 1),
            "risk_label": "높음" if score >= 45 else "주의" if score >= 22 else "낮음",
            "recommended_action": "담당자 추가 배정 또는 우선 처리 검토" if score >= 45 else "일일 처리량 모니터링",
            "samples": data["samples"],
        })
    rows.sort(key=lambda r: -r["score"])
    return {
        "pending_total": len(pending),
        "rows": rows[:top_k],
        "summary": f"현재 미완료 {len(pending)}건 중 병목 후보 {min(len(rows), top_k)}개 분야를 찾았습니다.",
    }


def simulate_assignment(
    applications: list[Any],
    *,
    staff_current: int = 5,
    staff_extra: int = 1,
    daily_capacity: float = 1.0,
    expedite_count: int = 0,
) -> dict[str, Any]:
    pending = [a for a in applications if getattr(a, "status", None) == "pending"]
    units = [max(1.0, float(getattr(a, "predicted_days", 5) or 5) / 5.0) for a in pending]
    workload = float(sum(units))
    before_capacity = max(0.1, staff_current * daily_capacity)
    after_capacity = max(0.1, (staff_current + staff_extra) * daily_capacity)
    before_days = workload / before_capacity
    priority_gain = min(workload * 0.18, expedite_count * 0.7)
    after_days = max(0.0, (workload - priority_gain) / after_capacity)
    reduction = before_days - after_days
    return {
        "pending_total": len(pending),
        "workload_units": round(workload, 1),
        "before": {
            "staff": staff_current,
            "capacity_per_day": round(before_capacity, 1),
            "estimated_clearance_days": round(before_days, 1),
        },
        "after": {
            "staff": staff_current + staff_extra,
            "capacity_per_day": round(after_capacity, 1),
            "estimated_clearance_days": round(after_days, 1),
            "expedite_count": expedite_count,
        },
        "effect": {
            "reduced_days": round(reduction, 1),
            "reduction_percent": int(round((reduction / before_days) * 100)) if before_days else 0,
        },
        "recommendation": "추가 배정 효과가 큽니다." if reduction >= 2 else "현재 병목은 크지 않지만 고위험 건 우선 처리를 권장합니다.",
    }





