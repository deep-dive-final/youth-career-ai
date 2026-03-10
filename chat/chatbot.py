import os
import asyncio
import time
import json
from typing import Annotated, TypedDict, List, Any
from openai import AsyncOpenAI
from google import genai
from google.genai import types
from utils.db import getMongoDbClient
from tavily import TavilyClient
from langgraph.graph import StateGraph, START, END
from dotenv import load_dotenv

# 1. 환경 설정 및 클라이언트 초기화
load_dotenv()
openai_client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))
gemini_client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
tavily_client = TavilyClient(api_key=os.getenv('TAVILY_API_KEY'))

# 2. 보조 함수
async def get_query_vector_async(text):
    try:
        res = await openai_client.embeddings.create(
            input=text,
            model="text-embedding-3-large"
        )
        return res.data[0].embedding
    except Exception as e:
        print(f"❌ 임베딩 생성 에러: {e}")
        return [0.0] * 3072

# 3. LangGraph 상태 정의
class PolicyState(TypedDict):
    messages: list[dict]
    user_query: str
    user_name: str
    user_profile: dict
    is_authenticated: bool
    is_policy: bool
    target_regions: list[str]
    query_vector: list[float]
    search_keyword: str
    web_res_raw: Any
    top_5: list[dict]
    max_score: float
    is_sufficient: bool
    final_answer: str
    start_time: float

# 4. 노드 정의

async def analyze_node(state: PolicyState):
    user_query = state["user_query"]
    profile = state.get("user_profile", {})
    history_context = "\n".join([f"{m['role']}: {m['content']}" for m in state["messages"][-2:]]) if len(state["messages"]) > 1 else ""

    tasks = [
        openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": f"문맥[{history_context}] 참고. JSON: {{'is_policy': true, 'regions': '지역명', 'search_keyword': '보정된 검색어'}}"}],
            response_format={"type": "json_object"}
        ),
        get_query_vector_async(user_query)
    ]
    intent_res, query_vector = await asyncio.gather(*tasks)
    analysis = json.loads(intent_res.choices[0].message.content)
    
    return {
        "is_policy": analysis.get("is_policy", True),
        "target_regions": [r.strip().replace("시", "").replace("도", "") for r in analysis.get("regions", "전국").split(',')],
        "query_vector": query_vector,
        "search_keyword": analysis.get("search_keyword", user_query)
    }

async def vector_search_node(state: PolicyState):
    db = getMongoDbClient()
    vector_results = list(db['policy_vectors'].aggregate([
        {"$vectorSearch": {
            "index": "vector_index_v2", 
            "path": "embedding_gemini_v2", 
            "queryVector": state["query_vector"], 
            "numCandidates": 50, "limit": 20
        }},
        {"$addFields": {"score": {"$meta": "vectorSearchScore"}}}
    ]))
    
    region_specific, nationwide, seen_titles = [], [], set()
    for doc in vector_results:
        meta = doc.get('metadata', {})
        title = meta.get('policy_name', '').strip()
        if title in seen_titles: continue
        
        region_val = meta.get('region', ['전국'])[0]
        item = {"title": title, "region": region_val, "content": doc.get('content_chunk_v2') or meta.get('support_content')}
        
        if state["target_regions"] and any(reg in region_val or reg in title for reg in state["target_regions"]):
            region_specific.append(item)
        elif any(k in region_val for k in ["전국", "중앙", "국가"]):
            nationwide.append(item)
        seen_titles.add(title)
        
    return {"top_5": (region_specific + nationwide)[:5], "max_score": vector_results[0].get('score', 0) if vector_results else 0}

async def verify_relevance_node(state: PolicyState):
    if not state.get("top_5") or state["max_score"] < 0.6:
        web_res = await asyncio.to_thread(tavily_client.search, query=state["search_keyword"], max_results=3)
        return {"is_sufficient": False, "web_res_raw": web_res}

    v_res = await openai_client.chat.completions.create(
        model="gpt-4o-mini", 
        messages=[
            {"role": "system", "content": "질문의 연도/지역/대상이 일치하면 YES, 아니면 NO라고 하세요."},
            {"role": "user", "content": f"질문: {state['user_query']}\n데이터: {[d['title'] for d in state['top_5']]}"}
        ],
        max_tokens=5, temperature=0
    )
    is_sufficient = "YES" in v_res.choices[0].message.content.strip().upper()
    
    if not is_sufficient:
        web_res = await asyncio.to_thread(tavily_client.search, query=state["search_keyword"], max_results=3)
        return {"is_sufficient": False, "web_res_raw": web_res}

    return {"is_sufficient": True}

async def generate_final_answer(state: PolicyState):
    is_sufficient = state["is_sufficient"]
    data_to_use = (state["top_5"] if is_sufficient else state["web_res_raw"].get('results', []))[:3]
    source_info = "내부 DB" if is_sufficient else "실시간 웹 검색"
    
    response = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": f"당신은 {source_info} 기반 정책 전문가입니다. 최대 3개만 요약하고 맺음말은 생략하세요."},
            {"role": "user", "content": f"데이터: {data_to_use}\n질문: {state['user_query']}"}
        ],
        temperature=0.5
    )
    print(f"📊 [LangGraph] 소요시간: {time.time()-state['start_time']:.2f}s")
    return {"final_answer": response.choices[0].message.content.strip()}

async def off_topic_node(state: PolicyState):
    return {"final_answer": "정책 상담과 관련된 질문을 해주시면 자세히 안내해 드릴게요! 😊"}

# 5. 그래프 조립
def route_intent(state: PolicyState):
    return "vector_search" if state["is_policy"] else "off_topic"

workflow = StateGraph(PolicyState)
workflow.add_node("analyze", analyze_node)
workflow.add_node("vector_search", vector_search_node)
workflow.add_node("verify", verify_relevance_node)
workflow.add_node("generate", generate_final_answer)
workflow.add_node("off_topic", off_topic_node)

workflow.add_edge(START, "analyze")
workflow.add_conditional_edges("analyze", route_intent, {"vector_search": "vector_search", "off_topic": "off_topic"})
workflow.add_edge("vector_search", "verify")
workflow.add_edge("verify", "generate")
workflow.add_edge("generate", END)
workflow.add_edge("off_topic", END)
app = workflow.compile()

# 6. 인터페이스 함수
async def get_AI_response(messages, user=None):
    is_auth = user.is_authenticated if user and not user.is_anonymous else False
    user_profile = {}
    if is_auth:
        try:
            db = getMongoDbClient()
            p = db['user_profiles'].find_one({"user_id": str(user.id)})
            if p: user_profile = {"age": p.get("age"), "job": p.get("job_status"), "region": p.get("region", "전국")}
        except: pass

    result = await app.ainvoke({
        "messages": messages, "user_query": messages[-1]['content'], 
        "user_name": user.username if is_auth else "고객", "user_profile": user_profile,
        "is_authenticated": is_auth, "start_time": time.time(), "is_sufficient": False,
        "target_regions": [user_profile.get("region")] if user_profile.get("region") else []
    })
    return result["final_answer"]