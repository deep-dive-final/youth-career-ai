import re
import os
import google.generativeai as genai  

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")  # 또는 settings.GEMINI_API_KEY

def _strip_emoji(text: str) -> str:
    if not isinstance(text, str):
        return str(text)
    text = re.sub(r"[^\w\s가-힣%-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def build_query_text(profile: dict) -> str:
    age = profile.get("age") or "알 수 없음"
    region = profile.get("region") or "전국"
    edu = profile.get("education_level") or "알 수 없음"
    edu_stat = profile.get("education_status") or "알 수 없음"
    job = profile.get("job_status") or "알 수 없음"
    income = profile.get("income_level") or "알 수 없음"

    # 관심 분야 (복수 선택)
    purpose = profile.get("interests") or profile.get("purpose") or []
    if isinstance(purpose, list):
        purpose_clean = [_strip_emoji(x) for x in purpose if str(x).strip()]
        seen = set()
        purpose_clean = [x for x in purpose_clean if not (x in seen or seen.add(x))]
        purpose_text = ", ".join(purpose_clean) if purpose_clean else "알 수 없음"
    else:
        purpose_text = _strip_emoji(str(purpose)) or "알 수 없음"

    return (
        f"사용자 상황 요약:\n"
        f"- 연령대: {age}\n"
        f"- 거주 지역: {region}\n"
        f"- 학력: {edu} ({edu_stat})\n"
        f"- 현재 상태: {job}\n"
        f"- 소득 기준: {income}\n"
        f"- 관심 분야: {purpose_text}\n\n"
        f"추천 요청:\n"
        f"{region}에 거주하는 {age} 청년이 현재 {job} 상태이며 "
        f"{edu} {edu_stat}이다. "
        f"소득은 {income} 수준이고, "
        f"{purpose_text} 관련 지원을 우선으로 받을 수 있는 "
        f"{region} 지역 정책 또는 전국 단위 청년 정책/지원사업을 추천해줘. "
        f"지역 제한이 있는 경우 반드시 {region} 적용 가능 여부를 고려해줘."
    )


# -------------------
# 추천 쿼리 임베딩 (Gemini)
# -------------------
def embed_query_gemini(text: str) -> list[float]:
    """
    ✅ policy_vectors를 만들 때와 동일한 모델/차원/방식으로 query 임베딩 생성
    - model: models/gemini-embedding-001
    - output_dimensionality: 3072
    - task_type: query (검색용)
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY가 설정되어 있지 않습니다.")

    genai.configure(api_key=GEMINI_API_KEY)

    model_name = "models/gemini-embedding-001"
    result = genai.embed_content(
        model=model_name,
        content=text,                 # ✅ query는 단일 문자열
        output_dimensionality=3072,    # ✅ policy_vectors와 차원 일치
        task_type="query",             # ✅ 검색용은 query
    )
    emb = result["embedding"]
    return emb

def vector_search_policies(db, query_vec: list[float], topk: int = 10):
    """
    policy_vectors.embedding_gemini 대상으로 벡터검색 후
    policy_id 기준으로 group해서 TopK 정책을 반환
    """
    if len(query_vec) != 3072:
        raise ValueError(f"Gemini embedding dim mismatch: {len(query_vec)} (expected 3072)")

    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index_v2",   # ✅ Atlas 인덱스 이름
                "path": "embedding_gemini_v2",
                "queryVector": query_vec,
                "numCandidates": 300,
                "limit": 80
            }
        },
        {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
        {"$sort": {"score": -1}},
        {"$group": {
            "_id": "$policy_id",
            "bestScore": {"$first": "$score"},
            "bestChunk": {"$first": "$content_chunk"},
            "bestChunkId": {"$first": "$chunk_id"},
            "metadata": {"$first": "$metadata"},
        }},
        {"$sort": {"bestScore": -1}},
        {"$limit": topk},

        {"$lookup": {
            "from": "policies",
            "localField": "_id",
            "foreignField": "_id",
            "as": "policy"
        }},
        {"$unwind": {"path": "$policy", "preserveNullAndEmptyArrays": True}},

        {"$project": {
            "_id": 0,
            "policy_id": "$_id",
            "score": "$bestScore",
            "reason_snippet": "$bestChunk",
            "chunk_id": "$bestChunkId",
            "metadata": 1,
            "policy": 1,
        }},
    ]

    return list(db.policy_vectors.aggregate(pipeline))



