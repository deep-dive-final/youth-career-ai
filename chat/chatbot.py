
# ══════════════════════════════════════════════════════════════
# 1. 임포트 & 환경설정
# ══════════════════════════════════════════════════════════════

import os
import asyncio
import time
import json
import re
import datetime
import logging
from typing import Annotated, TypedDict, List, Any

from openai import AsyncOpenAI
from utils.db import getMongoDbClient
from tavily import TavilyClient
from langgraph.graph import StateGraph, START, END
from dotenv import load_dotenv

import chat.cache as cache

logger = logging.getLogger(__name__)

# ── 환경 설정 ─────────────────────────────────────────────────
load_dotenv()

# ── Gemini 선택적 임포트 (패키지 미설치 시 OpenAI fallback) ──
try:
    from google import genai as _genai
    from google.genai import types as _gtypes
    _GEMINI_PKG = True
except ImportError:
    _genai = None
    _gtypes = None
    _GEMINI_PKG = False

# ── API 엔진 자동 감지 ────────────────────────────────────────
_GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
_OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")

USE_GEMINI = bool(_GEMINI_KEY) and _GEMINI_PKG
USE_OPENAI = bool(_OPENAI_KEY)

if not USE_GEMINI and not USE_OPENAI:
    raise RuntimeError(
        "GEMINI_API_KEY 또는 OPENAI_API_KEY 중 하나는 반드시 .env에 설정해야 합니다."
    )

logger.info(f"[LLM 엔진] Gemini={USE_GEMINI} / OpenAI={USE_OPENAI}")

# ── 클라이언트 초기화 ─────────────────────────────────────────
openai_client = AsyncOpenAI(api_key=_OPENAI_KEY) if USE_OPENAI else None
gemini_client = _genai.Client(api_key=_GEMINI_KEY) if USE_GEMINI else None

# Tavily (선택)
_TAVILY_KEY   = os.getenv("TAVILY_API_KEY", "")
tavily_client = TavilyClient(api_key=_TAVILY_KEY) if _TAVILY_KEY else None
if not tavily_client:
    logger.warning("[Tavily] API 키 없음 — 웹 검색 비활성화")

# 임베딩 차원: gemini-embedding-001 = 3072, text-embedding-3-large = 3072
EMBED_DIM   = 3072
LLM_MODEL   = "gemini-3-flash-preview" if USE_GEMINI else "gpt-4o-mini"
EMBED_MODEL = "gemini-embedding-001"   if USE_GEMINI else "text-embedding-3-large"


# ══════════════════════════════════════════════════════════════
# 2. 상수 & 딕셔너리
# ══════════════════════════════════════════════════════════════

# ── 키워드 (하이브리드 라우팅용) ──────────────────────────────
POLICY_HINTS = [
    # 기존
    "정책", "지원", "신청", "접수", "대상", "자격", "수당", "지원금", "사업", "취업", "면접",
    # 추가 — 청년 정책 관련 광범위 키워드
    "청년", "장학", "월세", "훈련", "창업", "도약", "내일", "적금",
    "국민취업", "일자리", "복지", "혜택", "공고", "모집", "바우처",
    "K-패스", "청년도약", "온통청년",
]
STATUS_KEYWORDS = ["모집중", "신청 링크", "신청기간", "언제까지", "마감", "방법"]

# 지역명 별칭 매핑
REGION_ALIASES = {
    "서울": ["서울", "서울시", "서울특별시"],
    "경기": ["경기", "경기도", "경기북부", "경기남부"],
    "부산": ["부산", "부산시", "부산광역시"],
    "인천": ["인천", "인천시", "인천광역시"],
    "대구": ["대구", "대구시", "대구광역시"],
    "광주": ["광주", "광주시", "광주광역시"],
    "대전": ["대전", "대전시", "대전광역시"],
    "울산": ["울산", "울산시", "울산광역시"],
    "세종": ["세종", "세종시", "세종특별자치시"],
    "강원": ["강원", "강원도", "강원특별자치도"],
    "충북": ["충북", "충청북도"],
    "충남": ["충남", "충청남도"],
    "전북": ["전북", "전라북도", "전북특별자치도"],
    "전남": ["전남", "전라남도"],
    "경북": ["경북", "경상북도"],
    "경남": ["경남", "경상남도"],
    "제주": ["제주", "제주도", "제주특별자치도"],
}

# 슬롯 역질문 문구
SLOT_QUESTIONS = {
    "지역":     "현재 거주하고 계신 지역이 어디인가요? (예: 서울, 경기, 부산)",
    "나이":     "나이가 어떻게 되시나요? (만 나이로 알려주세요)",
    "취업상태": "현재 취업 상태를 알려주세요. (재직중 / 구직중 / 학생 / 창업준비중)",
    "관심분야": "어떤 분야에 관심이 있으신가요? (취업, 창업, 교육, 자산형성 등)",
}

# 페르소나별 시스템 프롬프트
PERSONA_PROMPTS = {
    "회복형": (
        "당신은 공감 중심 커리어 상담사입니다. "
        "먼저 심리적 안정감을 제공하고, 급하지 않게 단계적으로 안내하세요. "
        "추천 우선순위: 심리상담 지원 → 교육·훈련 → 자산형성."
    ),
    "생계형": (
        "당신은 신속하고 실용적인 정책 안내 전문가입니다. "
        "해결책을 먼저 제시하고 상세한 신청 방법까지 안내하세요. "
        "추천 우선순위: 긴급 생계비 지원 → 단기 일자리 → 고정비 절감."
    ),
    "이직탐색형": (
        "당신은 전략적 커리어 파트너입니다. "
        "중장기 로드맵 관점에서 안내하고, 업스킬링 기회를 강조하세요. "
        "추천 우선순위: 재직자 교육 → 창업 지원 → 고용안정금."
    ),
    "일반형": (
        "당신은 청년 정책 전문가입니다. "
        "해요체로 친근하게 설명하고, 검색된 정책 정보만을 바탕으로 답변하세요."
    ),
}


# ══════════════════════════════════════════════════════════════
# 3. Gemini ↔ OpenAI 정규화 레이어
# ══════════════════════════════════════════════════════════════

class _ToolCall:
    """Gemini FunctionCall을 OpenAI ToolCall 인터페이스로 정규화.
    action_node가 엔진에 관계없이 동일한 코드로 동작하도록 보장."""

    def __init__(self, call_id: str, name: str, arguments: str):
        self.id       = call_id
        self.function = type("_Fn", (), {"name": name, "arguments": arguments})()

    @classmethod
    def from_gemini(cls, fc, idx: int) -> "_ToolCall":
        args_str = json.dumps(dict(fc.args), ensure_ascii=False)
        return cls(
            call_id   = f"gemini_{fc.name}_{idx}",
            name      = fc.name,
            arguments = args_str,
        )


def _to_gemini_messages(messages: list) -> list:
    """LangGraph state messages → Gemini Contents 리스트 변환.

    ⚠️ thought_signature 문제 방지 정책:
      Gemini thinking 모델은 function_call 응답에 thought_signature 를 포함시키는데,
      dict 로 저장·재구성하면 사라지므로 재전달 시 400 INVALID_ARGUMENT 발생.

      해결 원칙:
        - assistant with tool_calls → SKIP (function_call part 재전달 불가)
        - tool 결과 → 텍스트로 변환해서 user Content 로 전달
          (검색 결과는 Gemini 가 최종 답변 생성 시 반드시 필요하므로 제거하면 안 됨)
        - user / assistant(텍스트) → 그대로 전달
    """
    contents = []
    i = 0
    while i < len(messages):
        msg  = messages[i]
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", "")

        if role == "user":
            content = (msg.get("content") if isinstance(msg, dict)
                       else getattr(msg, "content", "")) or ""
            if content.strip():
                contents.append(_gtypes.Content(
                    role="user", parts=[_gtypes.Part(text=content)]
                ))
            i += 1

        elif role == "assistant":
            tool_calls = (msg.get("tool_calls") if isinstance(msg, dict)
                          else getattr(msg, "tool_calls", None)) or []

            if tool_calls:
                # function_call 메시지 자체는 건너뛰고, 바로 뒤 tool 결과를 텍스트로 수집
                i += 1
                tool_texts = []
                while i < len(messages):
                    tm      = messages[i]
                    tm_role = tm.get("role") if isinstance(tm, dict) else getattr(tm, "role", "")
                    if tm_role != "tool":
                        break
                    tc_content = (tm.get("content", "") if isinstance(tm, dict) else "") or ""
                    tool_texts.append(tc_content)
                    i += 1
                # tool 결과를 user 텍스트로 변환 (Gemini 가 검색 결과를 볼 수 있도록)
                if tool_texts:
                    combined = "다음은 도구 실행 결과입니다:\n" + "\n---\n".join(tool_texts)
                    contents.append(_gtypes.Content(
                        role="user", parts=[_gtypes.Part(text=combined)]
                    ))
            else:
                content = (msg.get("content") if isinstance(msg, dict)
                           else getattr(msg, "content", None)) or ""
                if content.strip():
                    contents.append(_gtypes.Content(
                        role="model", parts=[_gtypes.Part(text=content)]
                    ))
                i += 1

        elif role == "tool":
            # 단독 tool 메시지 (앞에 function_call 없는 경우) — 텍스트로 변환
            tc_content = (msg.get("content", "") if isinstance(msg, dict) else "") or ""
            if tc_content.strip():
                contents.append(_gtypes.Content(
                    role="user", parts=[_gtypes.Part(text=f"다음은 도구 실행 결과입니다:\n{tc_content}")]
                ))
            i += 1

        else:
            i += 1

    return contents


# ── Gemini Tool 스키마 (USE_GEMINI 일 때만 사용) ─────────────
if USE_GEMINI:
    GEMINI_TOOLS_DEF = _gtypes.Tool(
        function_declarations=[
            _gtypes.FunctionDeclaration(
                name        = "vector_search",
                description = "내부 정책 DB에서 정보를 검색합니다. 정책 관련 질문 시 사용하세요.",
                parameters  = _gtypes.Schema(
                    type       = "OBJECT",
                    properties = {
                        "query_text":     _gtypes.Schema(type="STRING", description="검색 키워드"),
                        "target_regions": _gtypes.Schema(
                            type="ARRAY", items=_gtypes.Schema(type="STRING"),
                            description="지역 리스트"
                        ),
                    },
                    required=["query_text", "target_regions"],
                ),
            ),
            _gtypes.FunctionDeclaration(
                name        = "web_search",
                description = "최신 정보나 외부 내용을 웹에서 검색합니다.",
                parameters  = _gtypes.Schema(
                    type       = "OBJECT",
                    properties = {"keyword": _gtypes.Schema(type="STRING", description="검색 키워드")},
                    required   = ["keyword"],
                ),
            ),
        ]
    )
else:
    GEMINI_TOOLS_DEF = None

# ── OpenAI Tool 스키마 ────────────────────────────────────────
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "vector_search",
            "description": "내부 정책 DB에서 정보를 검색합니다. 정책 관련 질문 시 사용하세요.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_text":     {"type": "string",  "description": "검색 키워드"},
                    "target_regions": {"type": "array", "items": {"type": "string"}, "description": "지역 리스트"},
                },
                "required": ["query_text", "target_regions"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "최신 정보나 외부 내용을 웹에서 검색합니다.",
            "parameters": {
                "type": "object",
                "properties": {"keyword": {"type": "string", "description": "검색 키워드"}},
                "required": ["keyword"],
            },
        },
    },
]


# ══════════════════════════════════════════════════════════════
# 4. 유틸 / 헬퍼 함수
# ══════════════════════════════════════════════════════════════

async def _embed(text: str) -> list:
    """임베딩 생성 — Gemini(gemini-embedding-001, 3072d) 또는 OpenAI(text-embedding-3-large, 3072d) 자동 선택."""
    try:
        if USE_GEMINI:
            res = await asyncio.to_thread(
                gemini_client.models.embed_content,
                model    = "gemini-embedding-001",
                contents = text,
            )
            return res.embeddings[0].values
        else:
            res = await openai_client.embeddings.create(
                input = text,
                model = "text-embedding-3-large",
            )
            return res.data[0].embedding
    except Exception as e:
        logger.error(f"[_embed] 실패: {e}")
        return [0.0] * EMBED_DIM


async def _generate(prompt: str) -> str:
    """단순 텍스트 생성 (단일 프롬프트 문자열) — Gemini 또는 OpenAI 자동 선택.
    analysis_prompt, summarize, fallback 등 대화 히스토리 없이 호출하는 곳에 사용."""
    try:
        if USE_GEMINI:
            res = await asyncio.to_thread(
                gemini_client.models.generate_content,
                model    = LLM_MODEL,
                contents = prompt,
            )
            return res.text or ""
        else:
            res = await openai_client.chat.completions.create(
                model    = LLM_MODEL,
                messages = [{"role": "user", "content": prompt}],
            )
            return res.choices[0].message.content or ""
    except Exception as e:
        logger.error(f"[_generate] 실패: {e}")
        return ""


# 지역명 정규화
def normalize_region(r: str) -> str:
    for canonical, aliases in REGION_ALIASES.items():
        if r.strip() in aliases:
            return canonical
    return r.strip()


# 관심분야 기반 재정렬
def _score_candidate(doc: dict, interest: str) -> int:
    score    = 0
    sub_cats = doc.get("sub_categories") or []
    if interest in sub_cats:                                     score += 10
    if interest in (doc.get("title") or ""):                    score += 4
    if interest in (doc.get("content") or ""):                  score += 2
    elig      = doc.get("eligibility") or {}
    elig_text = elig.get("text", "") if isinstance(elig, dict) else str(elig)
    if interest in elig_text:                                    score += 1
    return score


def rerank_results(candidates: list, interest: str) -> list:
    if not interest:
        return candidates[:5]
    scored = sorted(
        [(_score_candidate(c, interest), c) for c in candidates],
        key=lambda x: x[0], reverse=True,
    )
    return [doc for _, doc in scored][:5]


# 페르소나 결정
def resolve_persona(llm_hint: str, profile: dict) -> str:
    """우선순위: LLM 감지 → 설문 purpose → job_status → 기본값"""
    if llm_hint and llm_hint in PERSONA_PROMPTS and llm_hint != "일반형":
        return llm_hint
    purpose_list = profile.get("purpose") or []
    purpose      = " ".join(purpose_list) if isinstance(purpose_list, list) else str(purpose_list)
    if any(k in purpose for k in ["심리", "재도전", "회복"]):  return "회복형"
    if any(k in purpose for k in ["취업", "창업"]):            return "이직탐색형"
    if any(k in purpose for k in ["지원금", "생계"]):          return "생계형"
    JOB_MAP = {"구직중": "생계형", "창업준비중": "이직탐색형", "경단기": "회복형"}
    if matched := JOB_MAP.get(profile.get("job", "")):
        return matched
    return "일반형"


# 하위 호환 래퍼
async def get_query_vector_async(text: str) -> list:
    return await _embed(text)


# ── 대화 요약 ─────────────────────────────────────────────────
async def summarize_conversation(messages: List[dict], current_summary: str) -> str:
    if len(messages) <= 10:
        return current_summary
    to_summarize = messages[:-10]
    prompt = (
        "이전 대화 내용을 3~5문장으로 요약해줘. "
        "반드시 포함해야 할 항목:\n"
        "1. 사용자가 언급한 지역·나이·취업상태 등 슬롯 정보\n"
        "2. 사용자가 관심 보인 정책명 (있으면)\n"
        "3. 아직 해결 안 된 질문이나 요청\n"
        "기존 요약이 있으면 내용을 합쳐서 중복 없이 정리해줘.\n\n"
        f"기존 요약: {current_summary}\n"
        f"대상 대화: {str(to_summarize)}"
    )
    result = await _generate(prompt)
    return result if result else current_summary


# ══════════════════════════════════════════════════════════════
# 5. LangGraph 상태 정의
# ══════════════════════════════════════════════════════════════

class PolicyAgentState(TypedDict):
    messages:      Annotated[List[dict], lambda x, y: x + y]
    user_profile:  dict
    summary:       str
    start_time:    float
    tool_calls:    List[Any]
    persona_type:  str        # "회복형" | "생계형" | "이직탐색형" | "일반형"
    intent:        str        # "SEARCH" | "CONSULT" | "OOD"
    missing_slots: List[str]  # 미확인 슬롯 — agent_node system_prompt에 전달
    known_slots:   dict       # 대화 중 누적 수집된 슬롯 값 {"나이":27, "지역":"부산"}
    is_valid:      bool       # 팩트 검증 결과
    retry_count:   int        # 재시도 횟수 (최대 1회)


# ══════════════════════════════════════════════════════════════
# 6. 도구 실행 함수
# ══════════════════════════════════════════════════════════════

# 벡터 검색 (MongoDB $vectorSearch)
async def run_vector_search(query_text: str, target_regions: List[str], user_profile: dict = None):
    logger.info(f"[vector_search] ▶ 시작 | query='{query_text}' | regions_raw={target_regions}")
    target_regions = [normalize_region(r) for r in target_regions]
    logger.info(f"[vector_search] 지역 정규화 후: {target_regions}")

    logger.debug(f"[vector_search] 임베딩 생성 중... (model={EMBED_MODEL})")
    query_vector = await get_query_vector_async(query_text)
    logger.debug(f"[vector_search] 임베딩 완료 (dim={len(query_vector)})")
    db = getMongoDbClient()

    # policy_vectors → policies 조인 ($lookup)
    # 지역 지정 시 DB 레벨 필터 적용
    vector_filter = {}
    if target_regions and target_regions != ["전국"]:
        vector_filter = {"metadata.region": {"$in": target_regions}}
        logger.info(f"[vector_search] $vectorSearch filter 적용: {vector_filter}")

    vector_search_stage = {
        "$vectorSearch": {
            "index":         "vector_index_v2",
            "path":          "embedding_gemini_v3",
            "queryVector":   query_vector,
            "numCandidates": 100, "limit": 20,
        }
    }
    if vector_filter:
        vector_search_stage["$vectorSearch"]["filter"] = vector_filter

    vector_results = list(db["policy_vectors"].aggregate([
        vector_search_stage,
        {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
        {"$lookup": {
            "from":         "policies",
            "localField":   "policy_id",
            "foreignField": "_id",
            "as":           "policy_detail",
        }},
        {"$unwind": {"path": "$policy_detail", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "title":           {"$ifNull": ["$policy_detail.policy_name", "$metadata.policy_name"]},
            "region":          {"$arrayElemAt": ["$metadata.region", 0]},
            "content":         {"$ifNull": ["$content_chunk_v2", "$metadata.support_content"]},
            "policy_id":       {"$toString": "$policy_id"},  # ObjectId → str
            "eligibility":     "$policy_detail.eligibility",
            "application_url": "$policy_detail.application_url",
            "dates":           "$policy_detail.dates",
            "sub_categories":  "$metadata.sub_categories",
            "score":           1,
        }},
    ]))

    logger.info(f"[vector_search] MongoDB aggregate 결과: {len(vector_results)}건 (중복 제거 전)")
    top_scores = [(d.get("title", ""), round(d.get("score", 0), 4)) for d in vector_results[:3]]
    logger.info(f"[vector_search] 상위 score: {top_scores}")
    results = []
    seen    = set()
    for doc in vector_results:
        title = (doc.get("title") or "").strip()
        if not title or title in seen:
            continue
        results.append({
            "title":           title,
            "region":          doc.get("region") or "전국",
            "content":         doc.get("content") or "",
            "policy_id":       str(doc.get("policy_id") or ""),
            "eligibility":     doc.get("eligibility") or {},
            "application_url": doc.get("application_url") or "",
            "dates":           doc.get("dates") or {},
            "sub_categories":  doc.get("sub_categories") or [],
        })
        seen.add(title)
    logger.info(f"[vector_search] 중복 제거 후: {len(results)}건")

    # 관심분야 기준 재정렬
    interest = ""
    if user_profile:
        purpose_list = user_profile.get("purpose") or []
        interest     = purpose_list[0] if isinstance(purpose_list, list) and purpose_list else ""

    scored_log = sorted(
        [(_score_candidate(c, interest), c.get("title", "")) for c in results],
        reverse=True,
    )[:5]
    logger.info(f"[vector_search] rerank 점수: {scored_log}")

    top5   = rerank_results(results, interest)
    titles = [d.get("title", "") for d in top5]
    logger.info(f"[vector_search] ◀ 완료: {len(top5)}건 반환 | titles={titles}")
    return json.dumps(top5, ensure_ascii=False)


# ── 공식 도메인 필터 (웹 검색 신뢰도 향상) ───────────────────
OFFICIAL_DOMAINS = [
    "youthcenter.go.kr",   # 온통청년
    "work.go.kr",          # 워크넷
    "moel.go.kr",          # 고용노동부
    "bokjiro.go.kr",       # 복지로
    "gov.kr",              # 정부 공식 도메인
    "nhis.or.kr",          # 국민건강보험
    "nts.go.kr",           # 국세청
    "sbiz.or.kr",          # 소상공인진흥공단
    "kosmes.or.kr",        # 중소벤처기업진흥공단
    "kised.or.kr",         # 창업진흥원
]

# ── 웹 검색 ───────────────────────────────────────────────────
async def run_web_search(keyword: str):
    if not tavily_client:
        logger.warning("[web_search] Tavily 클라이언트 없음 — 스킵")
        return json.dumps([], ensure_ascii=False)

    refined_query = f"2026년 {keyword} 지원 사업 공고"
    logger.info(f"[web_search] ▶ 시작 | query='{refined_query}'")

    web_res = await asyncio.to_thread(
        tavily_client.search,
        query          = refined_query,
        max_results    = 5,
        include_domains= OFFICIAL_DOMAINS,   # 공식 도메인만
    )
    results = web_res.get("results", [])

    # 공식 도메인 결과 없으면 필터 없이 재시도 (신규 공고 대비)
    if not results:
        logger.warning("[web_search] 공식 도메인 결과 없음 → 필터 없이 재검색")
        web_res = await asyncio.to_thread(
            tavily_client.search,
            query      = refined_query,
            max_results= 5,
        )
        results = web_res.get("results", [])

    formatted_results = [
        {"title": r.get("title"), "content": r.get("content"), "url": r.get("url")}
        for r in results
    ]
    urls = [r.get("url", "") for r in formatted_results]
    logger.info(f"[web_search] ◀ 완료 | {len(formatted_results)}건 | urls={urls}")
    return json.dumps(formatted_results, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════
# 7. LangGraph 노드 함수
# ══════════════════════════════════════════════════════════════

async def agent_node(state: PolicyAgentState):
    logger.info(f"[agent_node] ▶ 시작 | msg수={len(state['messages'])} | persona={state.get('persona_type','일반형')} | retry={state.get('retry_count',0)}")
    new_summary         = await summarize_conversation(state["messages"], state.get("summary", ""))
    profile             = state.get("user_profile", {})
    today               = datetime.datetime.now().strftime("%Y년 %m월 %d일")
    persona_type        = state.get("persona_type", "일반형")
    persona_instruction = PERSONA_PROMPTS.get(persona_type, PERSONA_PROMPTS["일반형"])

    missing_slots = state.get("missing_slots", [])
    known_slots   = state.get("known_slots", {})

    slot_guide = (
        f"\n⚠️ 아직 파악 안 된 정보: {missing_slots}\n"
        "→ 답변 첫 부분에서 공감 한 마디를 건넨 뒤, 위 항목 중 하나만 자연스럽게 물어보세요. "
        "차갑게 바로 묻지 말고, 페르소나 말투에 맞게 녹여서 물어보세요."
        if missing_slots else ""
    )
    known_slots_info = (
        f"\n📋 대화 중 확인된 사용자 정보: {known_slots}\n"
        "→ 위 정보는 이미 파악된 것이므로 다시 묻지 마세요."
        if known_slots else ""
    )

    system_prompt = (
        f"{persona_instruction}\n\n"
        f"오늘 날짜는 {today}입니다.\n"
        f"사용자 프로필: {profile}. 이전 대화 요약: {new_summary}.\n"
        f"{known_slots_info}\n"
        f"{slot_guide}\n"
        "참조 원칙:\n"
        "1. **팩트 중심**: 없는 정책을 지어내지 마세요.\n"
        "2. **검색 우선**: 사용자가 정책 검색을 요청하면 부족한 정보가 있더라도 **반드시 먼저 vector_search를 호출**하세요. "
        "검색 결과를 보여주면서 부족한 정보를 자연스럽게 물어보세요. 역질문만 하고 검색을 안 하면 안 됩니다.\n"
        "3. **유연한 검색**: 특정 달에 맞는 공고가 없으면 유사 정책을 안내하세요.\n"
        "4. **요약 답변**: 핵심 정책 2~3개 위주로 간결하게 요약하세요.\n"
        "5. **출처 명시**: 참고한 URL을 포함하세요.\n"
        "6. **역질문**: 슬롯 정보가 부족하면 검색 결과와 함께 하나씩만 물어보세요. 역질문만 단독으로 하지 마세요.\n"
        "7. **맞춤 추천**: 슬롯이 모두 파악된 경우 각 정책이 이 사용자에게 왜 맞는지 근거를 제시하세요."
    )

    # ── Gemini 경로 ───────────────────────────────────────────
    if USE_GEMINI:
        gemini_msgs = _to_gemini_messages(state["messages"][-10:])

        # Gemini는 빈 contents를 허용하지 않음 — 최소 1개 보장
        if not gemini_msgs:
            gemini_msgs = [_gtypes.Content(role="user", parts=[_gtypes.Part(text="안녕하세요")])]

        res = await asyncio.to_thread(
            gemini_client.models.generate_content,
            model    = LLM_MODEL,
            contents = gemini_msgs,
            config   = _gtypes.GenerateContentConfig(
                system_instruction = system_prompt,
                tools              = [GEMINI_TOOLS_DEF],
                thinking_config    = _gtypes.ThinkingConfig(thinking_budget=0),
                # 한 턴에 1개 tool 만 호출하도록 제한 (과도한 병렬 호출 방지)
                tool_config        = _gtypes.ToolConfig(
                    function_calling_config=_gtypes.FunctionCallingConfig(mode="AUTO"),
                ),
            ),
        )

        # 응답 파싱: function_call 또는 text
        tool_calls   = []
        content_text = None
        if res.candidates and res.candidates[0].content.parts:
            for idx, part in enumerate(res.candidates[0].content.parts):
                if part.function_call:
                    tool_calls.append(_ToolCall.from_gemini(part.function_call, idx))
                elif part.text:
                    content_text = part.text

        # State에 저장할 메시지 딕셔너리 (정규화 포맷)
        msg_dict = (
            {"role": "assistant", "content": None,         "tool_calls": tool_calls}
            if tool_calls else
            {"role": "assistant", "content": content_text or ""}
        )
        logger.info(f"[agent_node/Gemini] ◀ 완료 | tool_calls={len(tool_calls)}개 | text='{(content_text or '')[:80]}'")
        return {
            "messages":   [msg_dict],
            "summary":    new_summary,
            "tool_calls": tool_calls,
        }

    # ── OpenAI 경로 ───────────────────────────────────────────
    else:
        response = await openai_client.chat.completions.create(
            model       = LLM_MODEL,
            messages    = [{"role": "system", "content": system_prompt}] + state["messages"][-10:],
            tools       = TOOLS_SCHEMA,
            tool_choice = "auto",
        )
        msg      = response.choices[0].message
        tc_count = len(msg.tool_calls) if msg.tool_calls else 0
        logger.info(f"[agent_node/OpenAI] ◀ 완료 | tool_calls={tc_count}개 | text='{(msg.content or '')[:80]}'")
        return {
            "messages":   [msg],
            "summary":    new_summary,
            "tool_calls": msg.tool_calls if msg.tool_calls else [],
        }


async def action_node(state: PolicyAgentState):
    """tool 실행 — _ToolCall / OpenAI ToolCall 모두 동일 인터페이스로 처리."""
    logger.info(f"[action_node] ▶ 시작 | tool_calls={len(state['tool_calls'])}개")
    results      = []
    user_profile = state.get("user_profile", {})
    for tc in state["tool_calls"]:
        args = json.loads(tc.function.arguments)
        logger.info(f"[action_node] 실행: {tc.function.name} | args={args}")
        if tc.function.name == "vector_search":
            content = await run_vector_search(args["query_text"], args["target_regions"], user_profile)
            result_data = json.loads(content)
            if len(result_data) == 0:
                logger.warning(f"[action_node] vector_search 결과 0건 → LLM이 web_search 호출 가능")
        else:
            content = await run_web_search(args.get("keyword", ""))
        logger.info(f"[action_node] {tc.function.name} 결과 길이: {len(content)}자")
        results.append({"role": "tool", "tool_call_id": tc.id, "content": content})
    logger.info(f"[action_node] ◀ 완료")
    return {"messages": results}


async def answer_grader(state: PolicyAgentState):
    """AI 답변이 검색 근거에 기반하는지 팩트 검증."""
    last_msg    = state["messages"][-1]
    last_answer = (last_msg.get("content", "") if isinstance(last_msg, dict)
                   else getattr(last_msg, "content", "")) or ""

    tool_outputs = []
    for m in state["messages"]:
        role    = m.get("role") if isinstance(m, dict) else getattr(m, "role", "")
        content = m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "")
        if role == "tool":
            tool_outputs.append(content or "")
    context = "\n".join(tool_outputs)

    # 도구 검색 결과가 없으면 대화형(역질문·공감) 응답 → 팩트 검증 불필요
    if not context.strip():
        logger.info("[answer_grader] 도구 결과 없음 → 대화형 응답, 검증 스킵 (is_valid=True)")
        return {"is_valid": True, "retry_count": state.get("retry_count", 0)}

    # 빈 답변이면 검증 의미 없음 → True 처리
    if not last_answer.strip():
        logger.info("[answer_grader] 빈 답변 → 검증 스킵 (is_valid=True)")
        return {"is_valid": True, "retry_count": state.get("retry_count", 0)}

    grader_prompt = (
        "당신은 AI 답변의 팩트를 검증하는 검수자입니다.\n"
        "아래 [근거 데이터]와 [AI 답변]을 비교해서 판단하세요.\n\n"
        "✅ is_valid = true 조건 (하나라도 해당하면 true):\n"
        "  1. 답변에 언급된 정책명이 [근거 데이터]의 title 필드에 실제로 존재함\n"
        "  2. 답변이 역질문·공감·안내 문장만으로 구성되어 정책명을 직접 언급하지 않음\n"
        "  3. 답변 내용이 [근거 데이터]의 content·eligibility·dates 필드와 일치함\n\n"
        "❌ is_valid = false 조건 (하나라도 해당하면 false):\n"
        "  1. 답변에 나온 정책명이 [근거 데이터] 어디에도 존재하지 않음\n"
        "  2. 신청 URL을 임의로 생성하거나 [근거 데이터]에 없는 URL을 제시함\n"
        "  3. 지원 금액·기간·자격 조건을 [근거 데이터]와 다르게 구체적으로 서술함\n\n"
        "⚠️ false로 판단하면 안 되는 경우:\n"
        "  - 날짜·금액 정보가 [근거 데이터]에 없어서 생략된 경우\n"
        "  - 표현이 약간 다르지만 의미가 동일한 경우 (예: '청년도약계좌' vs '청년 도약 계좌')\n\n"
        f"[근거 데이터]\n{context[:3000]}\n\n"
        f"[AI 답변]\n{last_answer[:1000]}\n\n"
        "반드시 JSON만 응답: {\"is_valid\": true 또는 false, \"reason\": \"판단 근거 한 줄\"}"
    )
    try:
        res_text = await _generate(grader_prompt)
        match    = re.search(r"\{.*\}", res_text, re.DOTALL)
        grade    = json.loads(match.group()) if match else {"is_valid": True}
        is_valid = grade.get("is_valid", True)
        retry    = state.get("retry_count", 0) + (0 if is_valid else 1)
        logger.info(f"[answer_grader] is_valid={is_valid} | reason={grade.get('reason', '')} | retry={retry}")
        return {"is_valid": is_valid, "retry_count": retry}
    except Exception as e:
        logger.warning(f"[answer_grader] 파싱 실패, 통과 처리: {e}")
        return {"is_valid": True}


def check_quality(state: PolicyAgentState):
    """팩트 검증 실패 시 agent 재시도 여부 결정 (최대 1회)."""
    is_valid = state.get("is_valid", True)
    retry    = state.get("retry_count", 0)
    if is_valid or retry >= 1:
        logger.info(f"[check_quality] → END (is_valid={is_valid}, retry={retry})")
        return END
    logger.info(f"[check_quality] → agent 재시도 (retry={retry})")
    return "agent"


def should_continue(state: PolicyAgentState):
    if state["tool_calls"]:
        return "action"
    return "grader"   # tool 없음 → 답변 검증 단계로


# ══════════════════════════════════════════════════════════════
# 8. 그래프 조립
# ══════════════════════════════════════════════════════════════

workflow = StateGraph(PolicyAgentState)
workflow.add_node("agent",  agent_node)
workflow.add_node("action", action_node)
workflow.add_node("grader", answer_grader)       # 팩트 검증 노드
workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent",  should_continue, {"action": "action", "grader": "grader"})
workflow.add_edge("action", "agent")
workflow.add_conditional_edges("grader", check_quality,   {END: END, "agent": "agent"})  # 재시도 or 종료
app = workflow.compile()


# ══════════════════════════════════════════════════════════════
# 9. 보조 포맷 함수
# ══════════════════════════════════════════════════════════════

# 정책 상세 정보 포맷 생성
def format_policy_detail(doc: dict) -> str:
    name      = doc.get("policy_name") or doc.get("title") or "정책명 없음"
    dates     = doc.get("dates") or {}
    apply     = dates.get("apply_period") or dates.get("apply_start") or "기간 정보 없음"
    elig      = doc.get("eligibility") or {}
    elig_text = elig.get("text", "자격 정보 없음") if isinstance(elig, dict) else str(elig)
    support   = doc.get("support_content") or doc.get("content") or "지원 내용 없음"
    url       = doc.get("application_url") or ""
    agency    = doc.get("supervising_agency") or ""
    return (
        f"📌 **{name}**\n\n"
        + (f"🏢 **주관기관:** {agency}\n" if agency else "")
        + f"📅 **신청기간:** {apply}\n"
        + f"👤 **지원대상:** {elig_text}\n"
        + f"💡 **지원내용:** {support}\n"
        + f"🔗 **신청링크:** {url or '별도 공지 예정'}"
    )


# ══════════════════════════════════════════════════════════════
# 10. 메인 인터페이스
# ══════════════════════════════════════════════════════════════

async def get_AI_response(session_id, messages, user=None):
    user_text = messages[-1]["content"]
    logger.info(f"[get_AI_response] ══════════ 요청 시작 ══════════")
    logger.info(f"[get_AI_response] session={session_id} | user='{getattr(user,'id','anon')}' | msg='{user_text[:80]}'")

    cached_data     = cache.get_cached_data(session_id) or {"messages": [], "summary": "", "known_slots": {}}
    current_summary = cached_data.get("summary", "")
    known_slots     = dict(cached_data.get("known_slots", {}))  # 이전 대화에서 수집된 슬롯
    today           = datetime.datetime.now().strftime("%Y년 %m월 %d일")

    # 사용자 프로필 조회
    user_profile = {}
    try:
        db          = getMongoDbClient()
        user_id_str = str(user.id) if (user and getattr(user, "is_authenticated", False)) else "anonymous"
        p           = db["user_profiles"].find_one({"user_id": user_id_str})
        if p:
            user_profile = {
                "age":     p.get("age"),
                "job":     p.get("job_status"),
                "region":  p.get("region", "전국"),
                "purpose": p.get("purpose", []),
            }
        logger.info(f"[get_AI_response] user_profile 조회: {user_id_str} → {user_profile}")
    except Exception as e:
        logger.warning(f"[get_AI_response] user_profile 조회 실패: {e}")

    # 의도 분석 — 슬롯 중복 질문 방지를 위해 최근 대화 이력 포함
    recent_history_lines = []
    if len(messages) > 1:
        for m in messages[-5:-1]:   # 현재 메시지 직전 최대 4턴
            r = m.get("role", "")
            c = m.get("content", "") or ""
            if r == "user":
                recent_history_lines.append(f"사용자: {c}")
            elif r == "assistant":
                recent_history_lines.append(f"챗봇: {c}")
    recent_history = "\n".join(recent_history_lines) if recent_history_lines else "없음"

    analysis_prompt = f"""오늘 날짜: {today}
대화 맥락: {current_summary}
최근 대화 이력:
{recent_history}
사용자 프로필: {user_profile}
현재 사용자 메시지: {user_text}

아래 JSON 형식으로만 응답하세요 (다른 텍스트 금지):
{{
  "is_policy":         true 또는 false,
  "intent":            "SEARCH" 또는 "CONSULT" 또는 "OOD",
  "needs_clarify":     true 또는 false,
  "missing_slots":     [],
  "slot_values":       {{}},
  "persona_type_hint": "회복형" 또는 "생계형" 또는 "이직탐색형" 또는 "일반형"
}}

정의:
- is_policy: 청년 정책·지원금·취업·창업 관련 질문이면 true
- intent: SEARCH=정책 검색, CONSULT=일반 고민 상담, OOD=범위 외
- needs_clarify: 지역/나이/취업상태 중 1개라도 모르면 true.
  단, 최근 대화 이력에서 사용자가 이미 답변한 항목은 알고 있는 것으로 처리하세요.
- missing_slots 예시: ["지역", "나이", "취업상태"].
  대화 이력에서 이미 확인된 슬롯은 절대 포함하지 마세요.
- slot_values: 현재 메시지 또는 최근 대화에서 확인된 슬롯 값만 포함.
  예: {{"나이": 27, "지역": "부산", "취업상태": "구직중"}}
  확인 안 된 항목은 포함하지 마세요.
- persona_type_hint: 대화 감정·맥락으로 추정한 사용자 유형"""

    analysis = {
        "is_policy": True, "intent": "SEARCH",
        "needs_clarify": False, "missing_slots": [], "persona_type_hint": "일반형",
    }
    try:
        res_text = (await _generate(analysis_prompt)).strip()
        match    = re.search(r"\{.*\}", res_text, re.DOTALL)
        if match:
            analysis = json.loads(match.group())
    except Exception as e:
        logger.warning(f"[analysis] 파싱 실패, fallback 사용: {e}")

    is_policy     = analysis.get("is_policy", True)
    intent        = analysis.get("intent", "SEARCH")
    needs_clarify = analysis.get("needs_clarify", False)
    missing_slots = analysis.get("missing_slots", [])
    persona_hint  = analysis.get("persona_type_hint", "일반형")
    persona_type  = resolve_persona(persona_hint, user_profile)

    # 슬롯 누적 (빈 값은 덮어쓰지 않음)
    new_slot_values = analysis.get("slot_values", {})
    for k, v in new_slot_values.items():
        if v is not None and v != "":
            known_slots[k] = v
    if new_slot_values:
        logger.info(f"[slots] 신규 감지: {new_slot_values} → 누적: {known_slots}")

    logger.info(
        f"[analysis] is_policy={is_policy} | intent={intent} | "
        f"needs_clarify={needs_clarify} | missing_slots={missing_slots} | persona={persona_type}"
    )

    # 라우팅: OOD / CONSULT / SEARCH
    if not is_policy and not any(k in user_text for k in POLICY_HINTS):
        logger.info("[route] ① OOD → 거부 메시지 반환")
        return {
            "answer":      "죄송합니다. 청년 정책 관련 상담만 가능합니다. 관심 있는 정책이나 지역을 말씀해 주세요!",
            "policy_list": [],
            "intent":      "OOD",
        }

    # 역질문은 agent_node가 페르소나 말투로 처리
    logger.info(f"[route] → REACT 실행 | persona={persona_type} | intent={intent} | missing_slots={missing_slots}")
    try:
        input_data = {
            "messages":      messages[-10:],
            "user_profile":  user_profile,
            "summary":       current_summary,
            "tool_calls":    [],
            "start_time":    time.time(),
            "persona_type":  persona_type,
            "intent":        intent,
            "missing_slots": missing_slots,
            "known_slots":   known_slots,    # 대화 중 누적된 슬롯
            "is_valid":      False,
            "retry_count":   0,
        }
        result = await app.ainvoke(input_data)

        # 마지막 유효 assistant 메시지 추출
        final_answer = ""
        for msg in reversed(result["messages"]):
            role    = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", "")
            content = (msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")) or ""
            if role == "assistant" and content.strip():
                final_answer = content
                break

        cache.set_cached_data(session_id, result["messages"], result.get("summary", current_summary), known_slots)

        # 검색 결과에서 policy_list 추출
        policy_list = []
        for msg in result["messages"]:
            if isinstance(msg, dict) and msg.get("role") == "tool":
                try:
                    items = json.loads(msg.get("content", "[]"))
                    if isinstance(items, list):
                        for item in items:
                            pid = item.get("policy_id", "")
                            if pid:
                                policy_list.append({
                                    "id":     pid,
                                    "name":   item.get("title", ""),
                                    "region": item.get("region", ""),
                                })
                except Exception:
                    pass

        logger.info(f"[get_AI_response] ══════════ 완료 (policy_list: {len(policy_list)}건) ══════════")
        return {"answer": final_answer, "policy_list": policy_list, "intent": intent}

    except Exception as e:
        logger.error(f"[agent] 실행 에러: {e}", exc_info=True)
        fallback_prompt = (
            f"오늘 날짜: {today}\n당신은 청년 정책 전문가입니다. "
            f"맥락: {current_summary}. 질문: {user_text}\n\n"
            "주의: 존재하지 않는 정책은 절대 추천하지 마세요. "
            "검색 결과가 없을 가능성이 크다면 유효한 공식 정책명(국민취업지원제도 등) 위주로 안내하세요."
        )
        fallback_answer = await _generate(fallback_prompt)
        return {"answer": fallback_answer, "policy_list": [], "intent": intent}
