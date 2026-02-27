"""
맞춤정책 검색 서비스
- Gemini AI 임베딩을 이용한 시맨틱 검색
- MongoDB Vector Search를 이용한 정책 매칭
"""

import os
import re
from datetime import date
from google import genai
from utils.db import getMongoDbClient
from django.conf import settings

# ============================================================================
# 상수
# ============================================================================

SCORE_THRESHOLD = 0.855  # 벡터 유사도 임계값 (0.855 미만은 검색 결과에서 제외)
AMOUNT_TEXT_RE = re.compile(
    r"(?:월|연|최대|최소)?\s*\d[\d,]*(?:\s*[~\-]\s*\d[\d,]*)?\s*(?:억|만원|천원|원)"
)
SUMMARY_SENTENCE_SPLIT_RE = re.compile(r"[.!?]\s+|\n+")


# ============================================================================
# 1️⃣ Gemini AI 클라이언트 설정
# ============================================================================

def get_genai_client():
    """
    Gemini API 클라이언트를 생성합니다.
    환경변수 또는 Django 설정에서 API 키를 찾습니다.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        api_key = getattr(settings, "GEMINI_API_KEY", None)
    if not api_key:
        api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        api_key = getattr(settings, "GOOGLE_API_KEY", None)

    if not api_key:
        raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY not found.")

    return genai.Client(api_key=api_key)


def _to_int_or_none(value):
    """
    숫자/문자 값을 int로 변환합니다.
    변환 불가/빈값은 None을 반환합니다.
    """
    if value is None:
        return None

    raw = str(value).strip().replace(",", "")
    if raw == "":
        return None

    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _format_money(value: int):
    return f"{value:,}원"


def _extract_amount_text(*texts):
    """
    텍스트에서 금액 패턴(만원/원 등)을 정규식으로 추출합니다.
    """
    for text in texts:
        if not text:
            continue
        match = AMOUNT_TEXT_RE.search(str(text))
        if match:
            return " ".join(match.group(0).split())
    return None


def _query_terms(query: str):
    """
    쿼리에서 의미 있는 토큰을 추출합니다.
    """
    if not query:
        return []
    terms = []
    for token in re.findall(r"[0-9A-Za-z가-힣]+", str(query).lower()):
        if len(token) >= 2:
            terms.append(token)
    return terms


def _normalize_text(value):
    if not value:
        return ""
    return " ".join(str(value).replace("\u00a0", " ").split())


def _extractive_summary(text: str, terms: list[str]):
    """
    간단한 추출형 요약:
    - 쿼리 토큰/금액 패턴이 포함된 문장을 우선 선택
    - 없으면 첫 문장 사용
    """
    normalized = _normalize_text(text)
    if not normalized:
        return None

    raw_sentences = [s.strip() for s in SUMMARY_SENTENCE_SPLIT_RE.split(normalized)]
    sentences = [s for s in raw_sentences if len(s) >= 8]
    if not sentences:
        return normalized[:180]

    best_idx = 0
    best_score = -1
    terms_lower = [t.lower() for t in terms]

    for idx, sentence in enumerate(sentences):
        sentence_lower = sentence.lower()
        score = 0
        if terms_lower:
            score += sum(1 for t in terms_lower if t in sentence_lower)
        if AMOUNT_TEXT_RE.search(sentence):
            score += 1
        if score > best_score:
            best_score = score
            best_idx = idx

    summary = sentences[best_idx]
    if best_idx + 1 < len(sentences):
        next_sentence = sentences[best_idx + 1]
        if len(summary) + len(next_sentence) <= 180:
            summary = f"{summary}. {next_sentence}"

    return summary[:220]


def _build_summary_text(policy: dict, terms: list[str]):
    """
    요약 우선순위:
    policy_summary -> content_chunk_v3 -> support_content -> content
    """
    candidates = [
        policy.get("policy_summary"),
        policy.get("content_chunk_v3"),
        policy.get("support_content"),
        policy.get("content"),
    ]

    for candidate in candidates:
        summary = _extractive_summary(candidate, terms)
        if summary:
            return summary

    return None


def _build_amount_text(policy: dict):
    """
    금액 표기 규칙:
    - max > 0: min > 0이면 range, 아니면 최대
    - max == 0 and min > 0: 최소
    - min == 0 and max == 0: 미표시
    - min/max 유효하지 않으면 텍스트에서 정규식 추출
    """
    earn = policy.get("earn") or {}
    min_amt = _to_int_or_none(earn.get("min_amt"))
    max_amt = _to_int_or_none(earn.get("max_amt"))

    if max_amt is not None:
        if max_amt > 0:
            if min_amt is not None and min_amt > 0:
                return f"{_format_money(min_amt)} ~ {_format_money(max_amt)}"
            return f"최대 {_format_money(max_amt)}"

        if max_amt == 0:
            if min_amt is not None and min_amt > 0:
                return f"최소 {_format_money(min_amt)}"
            return None

    if min_amt is not None and min_amt > 0:
        return f"최소 {_format_money(min_amt)}"

    return _extract_amount_text(
        earn.get("etc_content"),
        policy.get("support_content"),
    )


def _enrich_policy_item(item: dict):
    """
    프론트/평가 공통 사용 필드(doc_id, amount_text, summary_text)를 보강합니다.
    """
    if "_id" in item and "doc_id" not in item:
        item["doc_id"] = str(item.pop("_id"))
    elif "doc_id" in item:
        item["doc_id"] = str(item["doc_id"])

    item["amount_text"] = _build_amount_text(item)
    item["summary_text"] = _build_summary_text(item, item.get("_query_terms", []))
    item.pop("_query_terms", None)
    item.pop("policy_summary", None)
    item.pop("content_chunk_v3", None)
    item.pop("content", None)
    return item


# ============================================================================
# 2️⃣ 필터 조건 생성 함수들
# ============================================================================


def _build_policy_match(filters: dict | None):
    """
    사용자가 선택한 필터를 MongoDB 쿼리 조건으로 변환합니다.

    [DB 분석 기반 필드 매핑]
    - 지역        : region (최상위 list, 858개 전부 채워짐)
    - 직업상태    : job_type (최상위 list, 858개 전부 채워짐)
    - 나이        : eligibility.age_min / age_max (str 타입, '0'='제한없음')
    - 카테고리    : category (regex, 콤마 구분 가능)
    - 마감여부    : dates.apply_period (없으면 상시모집으로 간주)
    """
    if not filters:
        return {}

    conditions = []

    # ── 카테고리 (category - regex, 콤마 혼용 처리) ────────
    category = filters.get("category")
    if category and category != "all":
        conditions.append({
            "category": {"$regex": category, "$options": "i"}
        })

    # ── 서브 카테고리 (sub_category - 정확한 일치 또는 regex) ────────
    sub_category = filters.get("sub_category")
    if sub_category and sub_category != "all":
        conditions.append({
            "sub_category": sub_category
        })

    # ── 개인 조건 필터 ─────────────────────────────────────

    # 나이 (eligibility.age_min/max 는 str 타입이므로 숫자 비교는 $expr + $convert 사용)
    age = filters.get("age")
    if age is not None:
        try:
            age_int = int(age)
            conditions.append({
                "$or": [
                    {"eligibility.age_min": "0"},  # 연령 제한 없음
                    {
                        "$expr": {
                            "$let": {
                                "vars": {
                                    # 비정상 값은 비교에서 제외되도록 sentinel 사용
                                    "amin": {
                                        "$convert": {
                                            "input": "$eligibility.age_min",
                                            "to": "int",
                                            "onError": 999,
                                            "onNull": 999,
                                        }
                                    },
                                    "amax": {
                                        "$convert": {
                                            "input": "$eligibility.age_max",
                                            "to": "int",
                                            "onError": -1,
                                            "onNull": -1,
                                        }
                                    },
                                },
                                "in": {
                                    "$and": [
                                        {"$lte": ["$$amin", age_int]},
                                        {
                                            "$or": [
                                                {"$eq": ["$$amax", 0]},  # 최대 나이 제한 없음
                                                {"$gte": ["$$amax", age_int]},
                                            ]
                                        },
                                    ]
                                },
                            }
                        }
                    },
                ]
            })
        except (ValueError, TypeError):
            pass

    # 지역 (region 최상위 field - '전국' 포함)
    region = filters.get("region")
    if region and region != "all":
        conditions.append({
            "$or": [
                {"region": {"$in": [region]}},
                {"region": {"$in": ["전국"]}},
            ]
        })

    # 직업상태 (job_type 최상위 field - '제한없음' 포함)
    job_status = filters.get("jobStatus")
    if job_status and job_status != "all":
        conditions.append({
            "$or": [
                {"job_type": {"$in": [job_status]}},
                {"job_type": {"$in": ["제한없음"]}},
            ]
        })

    # 마감여부 (openOnly=true → 모집중인 정책만)
    open_only = filters.get("openOnly")
    if open_only:
        today_str = date.today().strftime("%Y%m%d")
        
        # 새로운 복합 조건 로직
        # 1. apply_period_type이 "마감"이면 무조건 제외
        # 2. apply_period_end 값이 오늘(<today_str)보다 작으면(과거면) 제외
        # 3. apply_period 값이 있고 종료일 파싱 시 오늘보다 작으면 제외
        # 위 제외 조건을 뚫고 남은 것들을 모집중으로 간주 
        
        # MongoDB 쿼리 구성:
        # AND 조건:
        # A. apply_period_type != "마감"
        # B. OR 조건:
        #    B-1. apply_period_end >= 오늘
        #    B-2. apply_period_end 없거나 비어 있고, apply_period에서 파싱한 날짜가 >= 오늘
        #    B-3. 둘 다 없으면 상시모집으로 간주 (통과)
        
        conditions.append({
            "$and": [
                # 1. 명시적 마감 제외
                {"dates.apply_period_type": {"$ne": "마감"}},
                
                # 2. 기한 체크 (OR 조건)
                {
                    "$or": [
                        # Case 1: apply_period_end 필드가 있고 오늘 이상인 경우
                        {
                            "$and": [
                                {"dates.apply_period_end": {"$exists": True}},
                                {"dates.apply_period_end": {"$ne": ""}},
                                {"dates.apply_period_end": {"$gte": today_str}}
                            ]
                        },
                        # Case 2: apply_period (문자열) 파싱 후 오늘 이상인 경우
                        {
                            "$and": [
                                {"dates.apply_period": {"$exists": True}},
                                {"dates.apply_period": {"$ne": ""}},
                                {
                                    "$expr": {
                                        "$gte": [
                                            {
                                                "$trim": {
                                                    "input": {
                                                        "$arrayElemAt": [
                                                            {"$split": ["$dates.apply_period", "~"]},
                                                            1
                                                        ]
                                                    }
                                                }
                                            },
                                            today_str
                                        ]
                                    }
                                }
                            ]
                        },
                        # Case 3: 기한 정보가 아예 없는 경우 (상시모집으로 간주)
                        {
                            "$and": [
                                {"$or": [{"dates.apply_period_end": {"$exists": False}}, {"dates.apply_period_end": ""}]},
                                {"$or": [{"dates.apply_period": {"$exists": False}}, {"dates.apply_period": ""}]}
                            ]
                        }
                    ]
                }
            ]
        })


    if not conditions:
        return {}
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def _lookup_match_from_policy_match(match: dict, prefix: str = "policy_detail"):
    """
    일반 필터 조건을 $lookup 후 사용할 조건으로 변환합니다.
    """
    if not match:
        return {}

    mapped = {}

    for key, value in match.items():
        if key.startswith("$"):
            if isinstance(value, list):
                mapped[key] = [_lookup_match_from_policy_match(item, prefix) for item in value]
            else:
                mapped[key] = value
        else:
            mapped[f"{prefix}.{key}"] = value

    return mapped


def _normalize_page(page: int, page_size: int):
    """
    페이지네이션 값을 안전한 범위로 조정합니다.
    """
    page = max(1, int(page))
    page_size = min(100, max(1, int(page_size)))
    return page, page_size


# ============================================================================
# 3️⃣ 메인 검색 함수
# ============================================================================

def search_policies(query: str = "", filters: dict = None, page: int = 1, page_size: int = 20):
    """
    정책 검색 메인 함수
    - 검색어 없으면: 필터링된 전체 목록 반환
    - 검색어 있으면: Gemini 임베딩 + Vector Search (score >= SCORE_THRESHOLD)
    """
    page, page_size = _normalize_page(page, page_size)
    query = (query or "").strip()
    terms = _query_terms(query)

    print(f"DEBUG: 검색 시작 - query='{query}', filters={filters}, page={page}", flush=True)

    # 목록 모드 projection
    projection = {
        "_id": 1,
        "policy_id": 1,
        "policy_name": 1,
        "category": 1,
        "sub_category": 1,
        "policy_summary": 1,
        "content_chunk_v3": 1,
        "content": 1,
        "support_content": 1,
        "supervising_agency": 1,
        "dates": 1,
        "eligibility": 1,
        "application_url": 1,
        "earn": 1,
    }

    skip = (page - 1) * page_size
    base_match = _build_policy_match(filters)

    # ── Case 1: 검색어 없음 ─────────────────────────────
    if not query:
        try:
            db = getMongoDbClient()
            policies_collection = db["policies"]

            total = policies_collection.count_documents(base_match)
            cursor = (
                policies_collection
                .find(base_match, projection)
                .sort("policy_name", 1)
                .skip(skip)
                .limit(page_size)
            )
            rows = list(cursor)
            for item in rows:
                item["_query_terms"] = terms
            results = [_enrich_policy_item(item) for item in rows]
        except Exception as e:
            return {"error": f"목록 조회 실패: {str(e)}"}

        return {
            "query": query,
            "filters": filters or {},
            "page": page,
            "page_size": page_size,
            "total": total,
            "results": results,
        }

    # ── Case 2: 검색어 있음 (벡터 검색) ────────────────
    try:
        client = get_genai_client()
        response = client.models.embed_content(
            model="gemini-embedding-001",
            contents=query,
        )

        if hasattr(response, "embeddings"):
            query_embedding = response.embeddings[0].values
        elif hasattr(response, "embedding"):
            query_embedding = response.embedding.values
        else:
            query_embedding = response.get("embedding", {}).get("values")

    except Exception as e:
        print(f"임베딩 생성 오류: {e}")
        return {"error": str(e)}

    try:
        db = getMongoDbClient()
    except Exception as e:
        return {"error": f"DB 연결 실패: {str(e)}"}

    # 유사도 임계값 적용 시 실제 결과가 적을 수 있으므로
    # numCandidates는 충분히 크게 유지
    num_candidates = 858  # 전체 문서 수 기준

    vector_search_stage = {
        "index": "vector_index_v2",
        "path": "embedding_gemini_v2",
        "queryVector": query_embedding,
        "numCandidates": num_candidates,
        "limit": num_candidates,
    }

    pipeline = [
        {"$vectorSearch": vector_search_stage},
        # ✅ 유사도 점수 추출 후 임계값 필터링 (0.80 미만 제거)
        {"$addFields": {"search_score": {"$meta": "vectorSearchScore"}}},
        {"$match": {"search_score": {"$gte": SCORE_THRESHOLD}}},
        {
            "$lookup": {
                "from": "policies",
                "localField": "policy_id",
                "foreignField": "_id",
                "as": "policy_detail",
            }
        },
        {"$unwind": "$policy_detail"},
    ]

    if base_match:
        pipeline.append({"$match": _lookup_match_from_policy_match(base_match)})

    # 키워드 검색 강화: 사용자가 입력한 query가 포함된 정책(이름 또는 키워드)에 가중치를 주거나 결과를 필터링
    # Vector Search 결과 내역에서 명시적 텍스트 매칭이 있는 경우를 상단으로 끌어올리거나 병합
    # 키워드 검색 강화: 사용자가 입력한 query가 포함된 정책에 가중치
    if query:
        pipeline.extend([
            {
                "$addFields": {
                    "text_match_bonus": {
                        "$cond": {
                            "if": {
                                "$or": [
                                    {"$regexMatch": {"input": "$policy_detail.policy_name", "regex": query, "options": "i"}},
                                    {"$regexMatch": {"input": {"$ifNull": ["$policy_detail.keywords", ""]}, "regex": query, "options": "i"}}
                                ]
                            },
                            "then": 0.5,
                            "else": 0
                        }
                    }
                }
            },
            {
                "$addFields": {
                    "final_score": {"$add": ["$search_score", "$text_match_bonus"]}
                }
            }
        ])

    # 💡 메모리 한도 초과(32MB 제한)를 막기 위해 정렬($sort) 전에 불필요한 큰 데이터(content 등)를 미리 $project로 제거합니다.
    pipeline.extend([
        {
            "$project": {
                "_id": 0,
                "policy_id": "$policy_detail.policy_id",
                "doc_id": {"$toString": "$policy_detail._id"},
                "policy_name": "$policy_detail.policy_name",
                "category": "$policy_detail.category",
                "sub_category": "$policy_detail.sub_category",
                "policy_summary": "$policy_detail.policy_summary",
                "content_chunk_v3": {
                    "$ifNull": ["$policy_detail.content_chunk_v3", "$content_chunk_v3"]
                },
                "content": "$policy_detail.content",
                "support_content": "$policy_detail.support_content",
                "supervising_agency": "$policy_detail.supervising_agency",
                "dates": "$policy_detail.dates",
                "eligibility": "$policy_detail.eligibility",
                "application_url": "$policy_detail.application_url",
                "earn": "$policy_detail.earn",
                "search_score": 1,
                "final_score": {"$ifNull": ["$final_score", "$search_score"]} # query가 없을 때를 대비
            }
        }
    ])

    if query:
        # query가 있을 때는 계산된 final_score 기준으로 정렬
        pipeline.append({
            "$sort": {"final_score": -1}
        })
    else:
        # query가 없으면 (벡터 검색 미수행 시) 이름순 정렬
        pipeline.append({
            "$sort": {"policy_name": 1}
        })

    pipeline.extend([
        {
            "$facet": {
                "meta": [{"$count": "total"}],
                "items": [{"$skip": skip}, {"$limit": page_size}],
            }
        }
    ])

    try:
        aggregated = list(db["policy_vectors"].aggregate(pipeline, allowDiskUse=True))
        payload = aggregated[0] if aggregated else {"meta": [], "items": []}
        total = payload["meta"][0]["total"] if payload["meta"] else 0
        rows = payload["items"]
        for item in rows:
            item["_query_terms"] = terms
        results = [_enrich_policy_item(item) for item in rows]
        print(f"DEBUG: 벡터 검색 결과 total={total} (score>={SCORE_THRESHOLD})", flush=True)
    except Exception as e:
        print(f"검색 실행 오류: {e}")
        return {"error": f"검색 실패: {str(e)}"}

    return {
        "query": query,
        "filters": filters or {},
        "page": page,
        "page_size": page_size,
        "total": total,
        "results": results,
    }
