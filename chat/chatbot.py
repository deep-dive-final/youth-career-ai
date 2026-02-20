import os
import asyncio
import time
from openai import AsyncOpenAI
from google import genai
from google.genai import types
from utils.db import getMongoDbClient

from dotenv import load_dotenv
load_dotenv()

openai_client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))
gemini_client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))

async def get_query_vector_async(text):
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, lambda: gemini_client.models.embed_content(
        model="gemini-embedding-001",
        contents=text,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY")
    ))
    return res.embeddings[0].values

async def get_AI_response(messages):
    overall_start = time.time()
    user_query = messages[-1]['content']
    
    # --- [수정] 1. GPT-4o를 이용한 다중 지역명 추출 ---
    try:
        region_extract_prompt = [
        {"role": "system", "content": """
        사용자의 질문에서 모든 지역명을 추출하세요. 
        특히, 사용자가 '시/군/구' 단위만 언급했다면 해당 지역이 속한 '도'나 '특별시/광역시'를 반드시 포함하여 콤마(,)로 구분해 답변하세요.
        
        예시:
        - '안산' -> '경기, 안산'
        - '강남' -> '서울, 강남'
        - '해운대' -> '부산, 해운대'
        - '창원' -> '경남, 창원'
        
        지역 관련 키워드가 전혀 없으면 '전국'이라고만 답변하세요.
        """},
        {"role": "user", "content": user_query}
    ]
        
        region_res = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=region_extract_prompt,
            max_tokens=20
        )
        
        # 추출된 결과를 리스트로 변환 (예: "경기, 안산" -> ["경기", "안산"])
        raw_regions = region_res.choices[0].message.content.strip().split(',')
        target_regions = [r.strip().replace("시", "").replace("도", "") for r in raw_regions if "전국" not in r]
    except:
        target_regions = []

    # --- 2. RAG 데이터 검색 (기존과 동일) ---
    query_vector = await get_query_vector_async(user_query)
    db = getMongoDbClient()
    vector_results = list(db['policy_vectors'].aggregate([
        {"$vectorSearch": {
            "index": "vector_index_v2", 
            "path": "embedding_gemini_v2", 
            "queryVector": query_vector, 
            "numCandidates": 100, 
            "limit": 50 # 다중 필터링을 위해 리미트를 조금 늘렸습니다.
        }}
    ]))

    # --- [수정] 3. 다중 지역 기반 필터링 및 매칭 ---
    region_specific, nationwide = [], []
    seen_titles = set()

    for doc in vector_results:
        meta = doc.get('metadata', {})
        title = meta.get('policy_name', '').strip()
        region_val = meta.get('region', ['전국'])[0]
        
        if title in seen_titles: continue
        
        item = {
            "title": title, 
            "region": region_val, 
            "content": doc.get('content_chunk_v2') or meta.get('support_content')
        }

        # [변경점] 리스트 내의 지역명 중 하나라도 포함되어 있는지 확인
        is_match = any(reg in region_val or reg in title for reg in target_regions)

        if target_regions and is_match:
            region_specific.append(item)
        elif any(k in region_val for k in ["전국", "중앙", "국가"]):
            nationwide.append(item)
        
        seen_titles.add(title)

    # 우선순위: 특정 지역 정책 -> 전국구 정책 순으로 합쳐서 상위 5개
    top_5 = (region_specific + nationwide)[:5]
    # 로그 출력용 상태값
    context_status = ", ".join(target_regions) if region_specific else "전국"

    # --- 4. GPT-4o 최종 답변 생성 ---
    api_messages = [
        {
            "role": "system", 
            "content": f"당신은 {context_status} 정책 요약 전문가입니다. 제공된 데이터를 기반으로 답변하세요."
        },
        {
            "role": "user", 
            "content": f"[참고 데이터]\n{top_5}\n\n질문: {user_query}\n\n위 데이터 중 가장 적합한 2개를 골라 다음 형식으로 요약하세요.\n### [정책명]\n* 👤 대상: 조건\n* 🎁 혜택: 상세내용\n* 📅 신청: 방법"
        }
    ]

    gen_start = time.time()
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=api_messages,
            max_completion_tokens=2000,
            temperature=0.7
        )
        ai_answer = response.choices[0].message.content
    except Exception as e:
        ai_answer = f"오류 발생: {str(e)}"
    
    print(f"\n📊 [분석] 추출지역: {context_status} | 전체시간: {time.time()-overall_start:.2f}s")
    return ai_answer