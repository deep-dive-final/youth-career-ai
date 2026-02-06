import os
import numpy as np
from google import genai
from google.genai import types
from utils.db import getMongoDbClient  

from dotenv import load_dotenv
load_dotenv()

# 1. 초기 설정
API_KEY = os.getenv('GEMINI_API_KEY')
client = genai.Client(api_key=API_KEY)

def get_query_vector(text):
    """3072차원 임베딩 추출 (gemini-embedding-001)"""
    res = client.models.embed_content(
        model="gemini-embedding-001",
        contents=text,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY")
    )
    return res.embeddings[0].values

def get_AI_response(messages):
    """
    views.py에서 전달받은 messages(대화 내역)를 바탕으로 RAG 답변 생성
    """
    print("[get_AI_response] start RAG process...")

    # 1. 마지막 질문 추출
    user_query = messages[-1]['content']
    
    # 2. 질문 벡터화
    query_vector = get_query_vector(user_query)
    
    # 3. MongoDB 벡터 검색 
    db = getMongoDbClient()
    vector_results = list(db['policy_vectors'].aggregate([
        {
            "$vectorSearch": {
                "index": "vector_index_v2",
                "path": "embedding_gemini_v2",
                "queryVector": query_vector,
                "numCandidates": 100,
                "limit": 10
            }
        },
        {
            "$lookup": {
                "from": "policies",
                "localField": "policy_id",
                "foreignField": "_id",
                "as": "policy_detail"
            }
        },
        { "$unwind": "$policy_detail" }
    ]))

    # 4. 검색된 정책 컨텍스트 구성
    candidate_context = ""
    for i, doc in enumerate(vector_results):
        detail = doc.get('policy_detail', {})
        agency = detail.get('supervising_agency', '정보 없음')
        title = detail.get('title', '제목 없음')
        content = detail.get('content_chunk_v2', str(detail)[:500])
        candidate_context += f"[{i}] 기관: {agency} | 제목: {title} | 내용: {content}\n"

    # 5. 이전 대화 요약 (최근 3개)
    history_text = ""
    for msg in messages[:-1][-3:]:
        role = "사용자" if msg['role'] == 'user' else "AI"
        history_text += f"{role}: {msg['content']}\n\n"

    # 6. 프롬프트 적용
    prompt = f"""
    당신은 대한민국 청년 정책 전문가입니다. 
    불필요한 인사말이나 서론("의도를 파악했습니다" 등)은 생략하고 바로 본론만 답변하세요.

    [이전 대화]:
    {history_text if history_text else "이전 대화 없음"}

    [새로 검색된 정책 후보]:
    {candidate_context}

    [답변 가이드라인]:
    **CASE A: 새로운 정책 추천을 원하는 경우 (예: "취업 정책 알려줘", "안산 정책 있어?")**
    1. [새로 검색된 정책 후보] 중 가장 적합한 것을 2개 이내로 선별하세요.
    2. 지역(안산 등)이 맞으면 [지역 특화], 국가 사업이면 [🚩국가 지원] 꼬리표를 붙이세요.
    3. 아래 포맷을 유지하세요:
       ### [정책명]
       * 👥 **대상**: 핵심만 1줄
       * 🎁 **혜택**: 핵심만 1줄
       * 📅 **신청**: 간략히
       ---

    **CASE B: 이전 답변 내용에 대해 구체적인 질문을 하는 경우 (예: "2번째 거 자세히", "신청 서류 뭐야?")**
    1. 새로 검색된 후보 리스트보다 [이전 대화]에 언급된 특정 정책의 내용을 상세히 설명하는 데 집중하세요.
    2. "2번째 정책"과 같이 숫자로 지칭하면, 이전 대화 리스트의 순서를 확인하여 정확한 정보를 전달하세요.
    3. '신청 프로세스', '필요 서류', '주의사항' 등을 친절하게 보충 설명하세요.
    4. 새로운 추천 리스트를 다시 나열하지 마세요.

    **공통 주의사항**:
    - 타 지역(거주지와 무관한 곳) 정책은 절대 추천하지 마세요.
    - 답변은 최대한 간결하고 가독성 있게 작성하세요.
    """

    # 7. Gemini 3 Flash 답변 생성
    response = client.models.generate_content(
        model="gemini-3-flash-preview", 
        contents=prompt
    )
    
    return response.text