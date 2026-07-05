"""Natural-language agent for KTL TestMate.

With OPENAI_API_KEY configured, this module uses the model to extract intent and
compose an answer grounded in local prediction/recommendation tools. Without a
key, it falls back to deterministic parsing and templated answers.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any, Optional

from . import ai_client
from .decision_support import deadline_success, risk_explanation
from .predictor import ProcDaysPredictor
from .recommender import recommend


def _columns(pred: ProcDaysPredictor) -> tuple[str, str, str]:
    cols = list(pred.sub_stats.columns)
    return cols[0], cols[1], cols[2]


def _priority(text: str) -> str:
    low = text.lower()
    if any(w in low for w in ["마감", "기한", "납기", "deadline", "까지", "맞춰"]):
        return "meet_deadline"
    if any(w in low for w in ["혼잡", "밀리", "덜 붐", "여유"]):
        return "avoid_congestion"
    if any(w in low for w in ["안정", "확실", "변동", "위험 낮"]):
        return "stable"
    return "fast"


def _parse_date_value(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _parse_dates(text: str, today: date) -> tuple[Optional[date], Optional[date]]:
    dates: list[date] = []
    for m in re.finditer(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})", text):
        dt = _parse_date_value(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if dt:
            dates.append(dt)
    for m in re.finditer(r"(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일", text):
        mo, day = int(m.group(1)), int(m.group(2))
        year = today.year if mo >= today.month else today.year + 1
        dt = _parse_date_value(year, mo, day)
        if dt:
            dates.append(dt)
    for m in re.finditer(r"(?<!\d)(\d{1,2})\s*월\s*(말|초|중순|하순)", text):
        mo, qual = int(m.group(1)), m.group(2)
        year = today.year if mo >= today.month else today.year + 1
        day = 28 if qual == "말" else 5 if qual == "초" else 15 if qual == "중순" else 24
        if qual == "말":
            nxt = date(year, mo, 28) + timedelta(days=4)
            day = (nxt - timedelta(days=nxt.day)).day
        dt = _parse_date_value(year, mo, day)
        if dt:
            dates.append(dt)
    receive = dates[0] if dates else None
    deadline = dates[1] if len(dates) >= 2 else None
    if dates and re.search(r"까지|마감|기한|납기|완료", text):
        deadline = dates[-1]
        if len(dates) == 1:
            receive = None
    if "오늘" in text and receive is None:
        receive = today
    if "내일" in text and receive is None:
        receive = today + timedelta(days=1)
    if "모레" in text and receive is None:
        receive = today + timedelta(days=2)
    if "다음 주" in text and receive is None:
        receive = today + timedelta(days=(7 - today.weekday()))
    return receive, deadline


def _resolve_category(text: str, pred: ProcDaysPredictor) -> Optional[tuple[str, str, str]]:
    biz_col, mid_col, sub_col = _columns(pred)
    df = pred.sub_stats.copy()
    count_col = "count" if "count" in df.columns else None
    if count_col:
        df = df.sort_values(count_col, ascending=False)
    best = None
    best_score = 0
    low = text.lower()
    for _, r in df.iterrows():
        biz, mid, sub = str(r[biz_col]), str(r[mid_col]), str(r[sub_col])
        score = 0
        if sub and sub.lower() in low:
            score += 12 + min(len(sub), 20)
        if mid and mid.lower() in low:
            score += 8 + min(len(mid), 12)
        if biz and biz.lower() in low:
            score += 5
        for token in re.findall(r"[A-Za-z0-9가-힣]{2,}", low):
            if token in sub.lower():
                score += 2
            if token in mid.lower():
                score += 1
        if score > best_score:
            best_score = score
            best = (biz, mid, sub)
    return best if best_score >= 5 else None


def _validate_category(pred: ProcDaysPredictor, biz: str | None, mid: str | None, sub: str | None) -> Optional[tuple[str, str, str]]:
    if not any([biz, mid, sub]):
        return None
    biz_col, mid_col, sub_col = _columns(pred)
    df = pred.sub_stats
    for _, r in df.iterrows():
        rb, rm, rs = str(r[biz_col]), str(r[mid_col]), str(r[sub_col])
        if sub and str(sub) == rs:
            return rb, rm, rs
        if mid and str(mid) == rm and (not biz or str(biz) == rb):
            return rb, rm, rs
    joined = " ".join(str(x) for x in [biz, mid, sub] if x)
    return _resolve_category(joined, pred)


def _catalog_sample(pred: ProcDaysPredictor, limit: int = 120) -> str:
    biz_col, mid_col, sub_col = _columns(pred)
    df = pred.sub_stats.copy()
    if "count" in df.columns:
        df = df.sort_values("count", ascending=False)
    lines = []
    for _, r in df.head(limit).iterrows():
        lines.append(f"- {r[biz_col]} > {r[mid_col]} > {r[sub_col]}")
    return "\n".join(lines)


def _llm_extract(text: str, pred: ProcDaysPredictor, today: date) -> dict[str, Any] | None:
    if not ai_client.settings()["enabled"]:
        return None
    messages = [
        {"role": "system", "content": "당신은 KTL 시험·검사 접수 상담 문장에서 구조화 정보를 추출하는 에이전트입니다. 반드시 JSON 객체만 반환하세요."},
        {"role": "user", "content": (
            f"오늘 날짜: {today.isoformat()}\n"
            f"사용자 문장: {text}\n\n"
            f"선택 가능한 분류 예시(가능하면 이 값 중에서 고르기):\n{_catalog_sample(pred)}\n\n"
            "JSON 스키마: {biz, mid, sub, receive_on, deadline, priority, intent, missing}. "
            "receive_on/deadline은 YYYY-MM-DD 또는 null. priority는 fast/stable/avoid_congestion/meet_deadline 중 하나. "
            "분류를 확신하지 못하면 null로 두고 missing에 필요한 질문을 넣으세요."
        )},
    ]
    res = ai_client.chat_json(messages, temperature=0.1, max_tokens=1200)
    if not res.get("ok"):
        return None
    return res.get("json")


def _to_date(v: Any) -> Optional[date]:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except Exception:
        return None


def _compose_llm_answer(text: str, facts: dict[str, Any]) -> Optional[str]:
    if not ai_client.settings()["enabled"]:
        return None
    messages = [
        {"role": "system", "content": (
            "당신은 KTL TestMate의 시험접수 일정 최적화 상담 AI입니다. "
            "제공된 예측/추천 결과만 근거로 답하고, 공식 확정 판정처럼 말하지 마세요. "
            "기업 신청자에게 바로 도움이 되도록 간결한 한국어로 답하세요."
        )},
        {"role": "user", "content": f"사용자 질문:\n{text}\n\n계산된 근거 데이터(JSON):\n{json.dumps(facts, ensure_ascii=False, default=str)}"},
    ]
    res = ai_client.chat_text(messages, temperature=0.25, max_tokens=900)
    if res.get("ok"):
        return str(res.get("content") or "").strip()
    return None


def answer(text: str, pred: ProcDaysPredictor, today: Optional[date] = None) -> dict[str, Any]:
    today = today or date.today()
    local_receive, local_deadline = _parse_dates(text, today)
    local_priority = _priority(text)
    local_triple = _resolve_category(text, pred)

    extracted = _llm_extract(text, pred, today) or {}
    llm_triple = _validate_category(pred, extracted.get("biz"), extracted.get("mid"), extracted.get("sub")) if extracted else None
    triple = llm_triple or local_triple
    receive = _to_date(extracted.get("receive_on")) or local_receive or today
    deadline = _to_date(extracted.get("deadline")) or local_deadline
    priority = extracted.get("priority") if extracted.get("priority") in {"fast", "stable", "avoid_congestion", "meet_deadline"} else local_priority

    if triple is None:
        missing = extracted.get("missing") if isinstance(extracted.get("missing"), list) else []
        msg = "시험 분류를 특정하지 못했습니다. 사업구분, 중분류 또는 소분류명을 한 가지 이상 포함해서 다시 질문해 주세요."
        if missing:
            msg += " 확인 필요: " + ", ".join(str(x) for x in missing[:3])
        return {
            "ok": False,
            "message": msg,
            "llm": ai_client.public_status(bool(extracted)),
            "extracted": {"receive_on": receive.isoformat() if receive else None, "deadline": deadline.isoformat() if deadline else None, "priority": priority},
        }

    biz, mid, sub = triple
    prediction = pred.predict(biz=biz, mid=mid, sub=sub, received_on=receive)
    recs = recommend(pred, biz=biz, mid=mid, sub=sub, earliest=receive,
                     latest=receive + timedelta(days=21), deadline=deadline,
                     priority=priority, n=5)
    risk = risk_explanation(pred, biz=biz, mid=mid, sub=sub, receive_on=receive, deadline=deadline)
    success = None
    if deadline:
        success = deadline_success(pred, biz=biz, mid=mid, sub=sub, receive_on=receive, deadline=deadline)

    facts = {
        "category": {"biz": biz, "mid": mid, "sub": sub},
        "receive_on": receive.isoformat(),
        "deadline": deadline.isoformat() if deadline else None,
        "priority": priority,
        "prediction": prediction,
        "deadline_success": success,
        "risk": {"risk_label": risk.get("risk_label"), "causes": risk.get("causes", [])[:4]},
        "recommendations": recs[:3],
    }
    llm_message = _compose_llm_answer(text, facts)
    if llm_message:
        message = llm_message
    else:
        parts = [
            f"[{biz} > {mid} > {sub}] {receive.isoformat()} 접수 기준 예상 소요는 {prediction['predicted_days']}일입니다.",
            f"예상 완료일은 {prediction['predicted_complete_at']}이고, 신뢰도는 {int(prediction['confidence'] * 100)}%, 혼잡도는 {prediction['congestion']}입니다.",
        ]
        if success:
            parts.append(f"마감일 {deadline.isoformat()} 기준 성공 확률은 {success['success_percent']}%({success['risk_label']})입니다.")
        if recs:
            top = recs[0]
            parts.append(f"추천 접수일은 {top['receive_on']}이며 예상 완료일은 {top['predicted_complete_at']}입니다.")
        message = " ".join(parts)

    return {
        "ok": True,
        "message": message,
        "llm": ai_client.public_status(bool(llm_message)),
        "extracted": {"biz": biz, "mid": mid, "sub": sub, "receive_on": receive.isoformat(), "deadline": deadline.isoformat() if deadline else None, "priority": priority},
        "prediction": prediction,
        "deadline_success": success,
        "risk": risk,
        "recommendations": recs,
    }
