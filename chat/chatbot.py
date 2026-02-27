import os
import asyncio
import time
from openai import AsyncOpenAI
from google import genai
from google.genai import types
from utils.db import getMongoDbClient
from tavily import TavilyClient  # Tavily 라이브러리 추가

from dotenv import load_dotenv
load_dotenv()

openai_client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))
gemini_client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
# Tavily 클라이언트 초기화
tavily_client = TavilyClient(api_key=os.getenv('TAVILY_API_KEY'))

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
    
    # --- 1. GPT-4o를 이용한 다중 지역명 추출 (기존 로직 유지) ---
    try:
        # 정책 관련 질문인지와 지역명을 동시에 판단하도록 프롬프트 고도화
        intent_region_prompt = [
            {"role": "system", "content": """
            사용자의 질문이 '정부/지자체 정책, 취업 지원, 복지, 수당' 등 정책 상담과 관련이 있는지 판단하고 지역명을 추출하세요.
            응답은 반드시 아래 JSON 형식으로만 답변하세요:
            {
              "is_policy": true 또는 false,
              "regions": "추출된 지역명들 (예: 경기, 안산 / 지역 없으면 '전국')",
              "reason": "판단 이유"
            }
            """},
            {"role": "user", "content": user_query}
        ]
        
        intent_res = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=intent_region_prompt,
            response_format={"type": "json_object"} # JSON 출력 강제
        )
        
        import json
        analysis = json.loads(intent_res.choices[0].message.content)
        
        # [체크] 정책 관련 질문이 아니라고 판단되면 즉시 우회 답변 반환
        if not analysis.get("is_policy", True):
            return f"안녕하세요! 저는 청년 정책 및 취업 지원 정보를 안내해 드리는 전문 상담사입니다. 현재 질문하신 '{user_query}' 내용은 정책 상담 범위를 벗어나 답변드리기 어렵습니다. 지원금, 취업 혜택 등 정책에 대해 물어봐 주시면 자세히 안내해 드릴게요! 😊"

        # [지역 추출] 기존 로직과 동일하게 지역명 리스트 변환
        raw_regions = analysis.get("regions", "전국").split(',')
        target_regions = [r.strip().replace("시", "").replace("도", "") for r in raw_regions if "전국" not in r]
        
    except Exception as e:
        print(f"의도 판별 오류: {e}")
        target_regions = [] # 에러 시 기본값 유지

    # --- 2. RAG 데이터 검색 (유사도 점수 포함하도록 수정) ---
    query_vector = await get_query_vector_async(user_query)
    db = getMongoDbClient()
    vector_results = list(db['policy_vectors'].aggregate([
        {"$vectorSearch": {
            "index": "vector_index_v2", 
            "path": "embedding_gemini_v2", 
            "queryVector": query_vector, 
            "numCandidates": 100, 
            "limit": 30 
        }},
        {"$addFields": {"score": {"$meta": "vectorSearchScore"}}}  # 충분성 판단을 위한 점수 추가
    ]))

    # --- [신규] 3. 검색 결과 충분성 판단 및 외부 검색 (Fallback) ---
    # 최고 점수가 0.7 미만이거나 결과가 없으면 외부 검색 실행
    max_score = vector_results[0].get('score', 0) if vector_results else 0
    is_sufficient = max_score >= 0.7 
    
    external_data = []
    if not is_sufficient:
        print(f"⚠️ 내부 데이터 점수 부족 ({max_score:.2f}). 외부 검색을 실행합니다.")
        # 정책 관련 도메인(gov.kr)으로 제한하여 검색
        search_query = f"site:gov.kr {', '.join(target_regions) if target_regions else ''} {user_query}"
        try:
            # Tavily 실시간 검색 수행
            web_search = await asyncio.to_thread(
                tavily_client.search, query=search_query, search_depth="advanced"
            )
            external_data = web_search.get('results', [])
        except Exception as e:
            print(f"외부 검색 오류: {e}")

    # --- 4. 데이터 필터링 및 매칭 (기존 로직 유지) ---
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

        is_match = any(reg in region_val or reg in title for reg in target_regions)

        if target_regions and is_match:
            region_specific.append(item)
        elif any(k in region_val for k in ["전국", "중앙", "국가"]):
            nationwide.append(item)
        
        seen_titles.add(title)

    top_5 = (region_specific + nationwide)[:5]
    context_status = ", ".join(target_regions) if region_specific else "전국"

    # --- 5. 조건부 답변 생성 (데이터 검증 및 출처 분기) ---
    
    # [추가] 내부 데이터 점수가 높더라도, 실제 질문과 관련이 있는지 GPT가 최종 검증 (리랭킹 대용)
    if is_sufficient:
        verification_prompt = [
            {"role": "system", "content": "당신은 검색 결과의 관련성을 판단하는 평가관입니다. 질문과 데이터가 관련이 있으면 'YES', 관련이 없거나 질문의 특정 고유명사(정책명 등)를 찾을 수 없으면 'NO'라고만 답하세요."},
            {"role": "user", "content": f"질문: {user_query}\n데이터 요약: {[d['title'] for d in top_5]}\n\n관련이 있습니까?"}
        ]
        try:
            v_res = await openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=verification_prompt,
                max_tokens=5,
                temperature=0
            )
            is_valid = v_res.choices[0].message.content.strip().upper()
            if "NO" in is_valid:
                print(f"⚠️ [검증 실패] 점수는 높으나({max_score:.2f}) 질문과 내용이 불일치합니다. 외부 검색을 시도합니다.")
                is_sufficient = False # 강제로 부족 상태로 전환하여 외부 검색 실행
                
                # 외부 검색이 아직 안 되었다면 실행 (Tavily 재호출)
                if not external_data:
                    search_query = f"site:gov.kr {', '.join(target_regions) if target_regions else ''} {user_query}"
                    web_search = await asyncio.to_thread(tavily_client.search, query=search_query, search_depth="advanced")
                    external_data = web_search.get('results', [])
        except:
            pass # 검증 에러 시 기존 점수 기준 유지

    # 최종 분기 처리
    if not is_sufficient and external_data:
        source_info = "정부24 및 실시간 웹 검색"
        data_to_use = external_data
        # 답변 끝에 출처를 붙이되, 정보가 없는 경우에 대한 예외 처리를 프롬프트에 추가
        system_instruction = f"""
        내부 DB에 정보가 부족하여 {source_info} 결과를 참고합니다. 
        만약 검색 결과에서도 사용자가 찾는 특정 정책명이 명확히 확인되지 않는다면, 
        억지로 답변하지 말고 '관련 정보를 찾을 수 없다'고 정중히 안내하세요.
        답변 끝에는 반드시 [출처: {source_info}]를 한 줄 띄우고 적어주세요.
        """
    elif not is_sufficient and not external_data:
        # 이 구간은 출처 없이 깔끔하게 안내만 나갑니다.
        return "죄송합니다. 현재 내부 DB 및 실시간 검색을 통해서도 해당 정책에 대한 정확한 정보를 확인하기 어렵습니다. 정책명이나 지역을 다시 확인해 주시면 감사하겠습니다. 😊"
    else:
        data_to_use = top_5
        system_instruction = f"당신은 {context_status} 정책 요약 전문가입니다. 제공된 데이터를 기반으로 답변하세요. 별도의 출처 문구는 적지 마세요."

    api_messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": f"[참고 데이터]\n{data_to_use}\n\n질문: {user_query}\n\n위 데이터 중 가장 적합한 2개를 골라 다음 형식으로 요약하세요.\n### [정책명]\n* 👤 대상: 조건\n* 🎁 혜택: 상세내용\n* 📅 신청: 방법"}
    ]

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

    # --- 6. 셀프 리플렉션 (답변 검토) ---
    reflection_prompt = f"""
    당신은 정책 답변 검증관입니다. 아래 [생성된 답변]이 [참고 데이터]와 일치하는지 확인하세요.
    
    [참고 데이터]: {data_to_use}
    [생성된 답변]: {ai_answer}
    
    확인 기준:
    1. 데이터에 없는 정책을 지어냈는가? (환각 확인)
    2. 신청 대상이나 혜택 금액이 데이터와 다른가?
    
    오류가 있다면 '수정된 내용'만 출력하고, 문제가 없다면 [생성된 답변]을 그대로 출력하세요. 
    '수정된 답변:' 이라는 머릿말이나 검토 결과에 대한 부연 설명은 절대 포함하지 마세요.
    """

    try:
        # 속도를 위해 4o-mini 모델 사용
        reflection_response = await openai_client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=[{"role": "system", "content": reflection_prompt}],
            temperature=0
        )
        final_answer = reflection_response.choices[0].message.content
    except Exception:
        final_answer = ai_answer  # 오류 시 원래 답변 유지
    
    # 모든 작업 완료 후 마지막에 로그 출력
    print(f"\n📊 [분석] 추출지역: {context_status} | 점수: {max_score:.4f} | 검증: {'통과' if is_sufficient else '실패(Fallback)'} | 전체시간: {time.time()-overall_start:.2f}s")
    
    return final_answer # 검토가 완료된 최종 답변 반환