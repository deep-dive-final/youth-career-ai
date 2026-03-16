import os
import asyncio
import time
import json
import datetime  # 날짜 계산을 위해 추가
from typing import Annotated, TypedDict, List, Any
from openai import AsyncOpenAI
from utils.db import getMongoDbClient
from tavily import TavilyClient
from langgraph.graph import StateGraph, START, END
from dotenv import load_dotenv
import chat.cache as cache

# 1. 환경 설정 및 클라이언트 초기화
load_dotenv()
openai_client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))
tavily_client = TavilyClient(api_key=os.getenv('TAVILY_API_KEY'))

# 키워드 (하이브리드 라우팅용)
POLICY_HINTS = ["정책", "지원", "신청", "접수", "대상", "자격", "수당", "지원금", "사업", "취업", "면접"]
STATUS_KEYWORDS = ["모집중", "신청 링크", "신청기간", "언제까지", "마감", "방법"]

# 2. 보조 함수: 임베딩 생성 및 대화 요약
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

async def summarize_conversation(messages: List[dict], current_summary: str):
    if len(messages) <= 10:
        return current_summary
    
    to_summarize = messages[:-10]
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "이전 대화 내용을 1~2문장으로 아주 짧게 요약해줘. 기존 요약이 있다면 내용을 합쳐줘."},
                {"role": "user", "content": f"기존 요약: {current_summary}\n대상 대화: {str(to_summarize)}"}
            ]
        )
        return response.choices[0].message.content
    except:
        return current_summary

# 3. LangGraph 상태 정의
class PolicyAgentState(TypedDict):
    messages: Annotated[List[dict], lambda x, y: x + y]
    user_profile: dict
    summary: str
    start_time: float
    tool_calls: List[Any]

# 4. 도구(Tool) 구현체 (출처 URL 포함하도록 수정)
async def run_vector_search(query_text: str, target_regions: List[str]):
    query_vector = await get_query_vector_async(query_text)
    db = getMongoDbClient()
    
    vector_results = list(db['policy_vectors'].aggregate([
        {"$vectorSearch": {
            "index": "vector_index_v2", 
            "path": "embedding_gemini_v2", 
            "queryVector": query_vector, 
            "numCandidates": 50, "limit": 20
        }},
        {"$addFields": {"score": {"$meta": "vectorSearchScore"}}}
    ]))
    
    results = []
    seen_titles = set()
    for doc in vector_results:
        meta = doc.get('metadata', {})
        title = meta.get('policy_name', '').strip()
        if title in seen_titles: continue
        
        # 실제 DB에 출처 URL 필드가 있다면 추가 (예: meta.get('url'))
        results.append({
            "title": title, 
            "region": meta.get('region', ['전국'])[0], 
            "content": doc.get('content_chunk_v2') or meta.get('support_content')
        })
        seen_titles.add(title)
        
    return json.dumps(results[:5], ensure_ascii=False)

async def run_web_search(keyword: str):
    refined_query = f"2026년 {keyword} 지원 사업 공고" 
    web_res = await asyncio.to_thread(tavily_client.search, query=refined_query, max_results=5) # 결과 개수 늘림
    
    formatted_results = []
    for r in web_res.get('results', []):
        formatted_results.append({
            "title": r.get('title'),
            "content": r.get('content'),
            "url": r.get('url')
        })
    return json.dumps(formatted_results, ensure_ascii=False)

# 5. OpenAI Tool 스키마 정의 (동일)
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "vector_search",
            "description": "내부 정책 DB에서 정보를 검색합니다. 정책 관련 질문 시 사용하세요.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_text": {"type": "string", "description": "검색 키워드"},
                    "target_regions": {"type": "array", "items": {"type": "string"}, "description": "지역 리스트"}
                },
                "required": ["query_text", "target_regions"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "최신 정보나 외부 내용을 웹에서 검색합니다.",
            "parameters": {
                "type": "object",
                "properties": {"keyword": {"type": "string", "description": "검색 키워드"}},
                "required": ["keyword"]
            }
        }
    }
]

# 6. 노드 정의 (할루시네이션 방지 프롬프트 강화)
async def agent_node(state: PolicyAgentState):
    new_summary = await summarize_conversation(state["messages"], state.get("summary", ""))
    profile = state.get("user_profile", {})
    
    # 오늘 날짜 정보 주입
    today = datetime.datetime.now().strftime("%Y년 %m월 %d일")
    
    system_prompt = (
        f"당신은 청년 정책 전문가입니다. 오늘 날짜는 {today}입니다.\n"
        f"사용자 프로필: {profile}. 이전 대화 요약: {new_summary}.\n\n"
        "참조 원칙:\n"
        "1. **팩트 중심**: 없는 정책을 지어내지 마세요. 하지만 질문과 완벽히 일치하는 명칭이 없더라도, **맥락상 유사한 정책(예: 경기도 청년 취업 지원 등)**이 검색된다면 이를 바탕으로 답변하세요.\n"
        "2. **유연한 검색**: 특정 달(2~3월)에 딱 맞는 공고가 없으면, 현재 모집 중이거나 곧 시작될 유사 정책을 안내하세요.\n"
        "3. **요약 답변**: 핵심 정책 2~3개 위주로 간결하게 요약하세요.\n"
        "4. **출처 명시**: 반드시 참고한 URL을 포함하세요."
    )
    
    response = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": system_prompt}] + state["messages"][-10:],
        tools=TOOLS_SCHEMA,
        tool_choice="auto"
    )
    
    msg = response.choices[0].message
    return {
        "messages": [msg],
        "summary": new_summary,
        "tool_calls": msg.tool_calls if msg.tool_calls else []
    }

async def action_node(state: PolicyAgentState):
    results = []
    for tc in state["tool_calls"]:
        args = json.loads(tc.function.arguments)
        if tc.function.name == "vector_search":
            content = await run_vector_search(args['query_text'], args['target_regions'])
        else:
            content = await run_web_search(args['keyword'])
            
        results.append({"role": "tool", "tool_call_id": tc.id, "content": content})
    return {"messages": results}

# 7. 그래프 조립 (동일)
def should_continue(state: PolicyAgentState):
    if state["tool_calls"]: return "action"
    return END

workflow = StateGraph(PolicyAgentState)
workflow.add_node("agent", agent_node)
workflow.add_node("action", action_node)
workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent", should_continue, {"action": "action", END: END})
workflow.add_edge("action", "agent")
app = workflow.compile()

# 8. 인터페이스 함수 (Fallback 로직에도 할루시네이션 방지 적용)
async def get_AI_response(session_id, messages, user=None):
    cached_data = cache.get_cached_data(session_id) or {"messages": [], "summary": ""}
    current_summary = cached_data.get("summary", "")
    user_text = messages[-1]["content"]
    today = datetime.datetime.now().strftime("%Y년 %m월 %d일")
    
    user_profile = {}
    try:
        db = getMongoDbClient()
        p = db['user_profiles'].find_one({"user_id": "test_user"}) 
        if p: user_profile = {"age": p.get("age"), "job": p.get("job_status"), "region": p.get("region", "전국")}
    except: pass

    # 의도 분석
    analysis_prompt = f"오늘 날짜: {today}\n맥락: {current_summary}\n질문: {user_text}\n정책 관련 질문인지 판단하여 {{\"is_policy\": true/false}} 형식으로 답하세요."
    is_policy = True
    try:
        res = await openai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "system", "content": analysis_prompt}])
        is_policy = '"is_policy": true' in res.choices[0].message.content.lower()
    except: pass

    if not is_policy and not any(k in user_text for k in POLICY_HINTS):
        return "죄송합니다. 청년 정책 관련 상담만 가능합니다. 관심 있는 정책이나 지역을 말씀해 주세요!"

    try:
        input_data = {"messages": messages[-10:], "user_profile": user_profile, "summary": current_summary, "tool_calls": []}
        result = await app.ainvoke(input_data)
        final_answer = result["messages"][-1].content
        cache.set_cached_data(session_id, result["messages"], result.get("summary", current_summary))
        return final_answer

    except Exception as e:
        print(f"❌ 에이전트 실행 에러: {e}")
        # Fallback에서도 팩트 체크 강화
        fallback_prompt = (
            f"오늘 날짜: {today}\n당신은 청년 정책 전문가입니다. 맥락: {current_summary}. 질문: {user_text}\n\n"
            "주의: 존재하지 않는 정책은 절대 추천하지 마세요. 검색 결과가 없을 가능성이 크다면 유효한 공식 정책명(국민취업지원제도 등) 위주로 안내하세요."
        )
        fallback_res = await openai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "system", "content": fallback_prompt}])
        return fallback_res.choices[0].message.content