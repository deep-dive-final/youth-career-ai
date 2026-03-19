import os
import asyncio
import time
import json
import datetime
from typing import Annotated, TypedDict, List, Any
from openai import AsyncOpenAI
from utils.db import getMongoDbClient
from tavily import TavilyClient
from langgraph.graph import StateGraph, START, END
from dotenv import load_dotenv
import chat.cache as cache
import google.generativeai as genai  

# 1. 환경 설정 및 클라이언트 초기화
load_dotenv()
openai_client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))
tavily_client = TavilyClient(api_key=os.getenv('TAVILY_API_KEY'))
genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))

POLICY_HINTS = ["정책", "지원", "신청", "접수", "대상", "자격", "수당", "지원금", "사업", "취업", "면접"]

# 2. 보조 함수: Gemini 임베딩 생성 및 대화 요약
async def get_query_vector_async(text):
    try:
        result = await asyncio.to_thread(
            genai.embed_content,
            model="models/gemini-embedding-001",
            content=text,
            task_type="retrieval_query",
            output_dimensionality=3072 
        )
        return result['embedding']
    except Exception as e:
        print(f"❌ Gemini 임베딩 생성 에러: {e}")
        return [0.0] * 3072

async def summarize_conversation(messages: List[dict], current_summary: str):
    if len(messages) <= 10:
        return current_summary
    to_summarize = messages[:-10]
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "이전 대화 내용을 짧게 요약해줘."},
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
    tool_calls: List[Any]
    is_valid: bool
    retry_count: int

# 4. 도구(Tool) 구현체
async def run_vector_search(query_text: str, target_regions: List[str]):
    query_vector = await get_query_vector_async(query_text)
    db = getMongoDbClient()
    
    vector_results = list(db['policy_vectors'].aggregate([
        {"$vectorSearch": {
            "index": "vector_index_v2", 
            "path": "embedding_gemini_v3",
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
        results.append({
            "title": title, 
            "region": meta.get('region', ['전국'])[0], 
            "content": doc.get('content_chunk_v2') or meta.get('support_content')
        })
        seen_titles.add(title)
    return json.dumps(results[:5], ensure_ascii=False)

async def run_web_search(keyword: str):
    web_res = await asyncio.to_thread(tavily_client.search, query=f"2026년 {keyword} 공고", max_results=5)
    formatted = [{"title": r.get('title'), "content": r.get('content'), "url": r.get('url')} for r in web_res.get('results', [])]
    return json.dumps(formatted, ensure_ascii=False)

# 5. OpenAI Tool 스키마 정의
TOOLS_SCHEMA = [
    {"type": "function", "function": {"name": "vector_search", "description": "내부 정책 DB 검색", "parameters": {"type": "object", "properties": {"query_text": {"type": "string"}, "target_regions": {"type": "array", "items": {"type": "string"}}}, "required": ["query_text", "target_regions"]}}},
    {"type": "function", "function": {"name": "web_search", "description": "최신 정보 웹 검색", "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}}, "required": ["keyword"]}}}
]

# 6. 노드 정의
async def agent_node(state: PolicyAgentState):
    new_summary = await summarize_conversation(state["messages"], state.get("summary", ""))
    profile = state.get("user_profile", {})
    today = datetime.datetime.now().strftime("%Y년 %m월 %d일")
    
    system_prompt = (
        f"당신은 청년 정책 전문가입니다. 오늘 날짜는 {today}입니다.\n"
        f"사용자 프로필: {profile}. 이전 대화 요약: {new_summary}.\n\n"
        
        "### [검색 실행 우선순위 - 필수 준수]\n"
        "1. **Step 1 (내부 검색)**: 정책 관련 질문 시 반드시 **가장 먼저 `vector_search`를 호출**하세요.\n"
        "2. **Step 2 (외부 검색 판단)**: 내부 결과가 부족하거나 '2026년 최신 공고 상태' 보완이 필요할 때만 `web_search`를 호출하세요.\n\n"

        "### [절대 금지 사항 - 환각 방지]\n"
        "1. 질문받은 정책명이 검색 결과에 **문자 그대로(Exactly)** 없다면, 절대 실존하는 것처럼 답변하지 마세요.\n"
        "2. 데이터에 없으면 '공식적으로 존재하지 않습니다'라고 명확히 밝히고, 유사 정책을 '대안'으로 안내하세요.\n\n"

        "### [가독성 및 출력 규칙 - URL 관리]\n"
        "1. **URL 직접 노출 금지**: 긴 URL(https://...)을 본문에 그대로 적지 마세요. 화면 레이아웃이 망가집니다.\n"
        "2. **하이퍼링크 활용**: 링크가 필요하다면 반드시 `[공고 확인하기](URL)` 또는 `[상세 정보](URL)` 형식의 마크다운 하이퍼링크를 사용하세요.\n"
        "3. **단계적 정보 제공**: 첫 답변은 정책 요약 위주로 하고, 사용자가 요청할 때 상세 링크를 제공하는 것을 권장합니다.\n\n"

        "### [상담 강화 지침]\n"
        "1. 답변 마지막에는 항상 사용자가 다음에 궁금해할 만한 '구체적인 질문'을 제안하세요. (예: 신청 서류, 신청 링크, 혹은 유사한 다른 정책 추천)\n"
        "2. 사용자가 미취업자/대학생 등 특정 상태라면, 중복 수혜 주의사항을 한 줄 덧붙여주세요."
    )
    
    response = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": system_prompt}] + state["messages"][-10:],
        tools=TOOLS_SCHEMA,
        tool_choice="auto"
    )
    msg = response.choices[0].message
    return {"messages": [msg], "summary": new_summary, "tool_calls": msg.tool_calls if msg.tool_calls else []}

async def action_node(state: PolicyAgentState):
    results = []
    print(f"\n--- 🔍 도구 실행 로그 ({datetime.datetime.now().strftime('%H:%M:%S')}) ---")
    for tc in state["tool_calls"]:
        args = json.loads(tc.function.arguments)
        tool_name = tc.function.name
        emoji = "📁" if tool_name == "vector_search" else "🌐"
        print(f"{emoji} 실행: {tool_name} | 키워드: {args.get('query_text') or args.get('keyword')}")
        
        content = await run_vector_search(args['query_text'], args['target_regions']) if tool_name == "vector_search" else await run_web_search(args['keyword'])
        results.append({"role": "tool", "tool_call_id": tc.id, "content": content})
    print(f"--- ✅ 완료 ---\n")
    return {"messages": results}

async def answer_grader(state: PolicyAgentState):
    last_answer = state["messages"][-1].content if hasattr(state["messages"][-1], 'content') else state["messages"][-1].get('content', '')
    
    tool_outputs = []
    for m in state["messages"]:
        m_role = getattr(m, 'role', None) if not isinstance(m, dict) else m.get('role')
        m_content = getattr(m, 'content', None) if not isinstance(m, dict) else m.get('content', '')
        if m_role == "tool":
            tool_outputs.append(m_content)
            
    context = "\n".join(tool_outputs)
    grader_prompt = (
        "정책 명칭이 데이터에 없거나 날짜를 지어냈다면 무조건 false입니다.\n"
        f"[근거 데이터]\n{context}\n\n[AI 답변]\n{last_answer}\n"
        "반드시 JSON 응답: {\"is_valid\": true/false}"
    )
    try:
        res = await openai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "system", "content": grader_prompt}], response_format={"type": "json_object"})
        grade = json.loads(res.choices[0].message.content)
        return {"is_valid": grade.get("is_valid", True), "retry_count": state.get("retry_count", 0) + (0 if grade.get("is_valid") else 1)}
    except: return {"is_valid": True}

# 7. 그래프 조립
def should_continue(state: PolicyAgentState):
    return "action" if state["tool_calls"] else "grader"

def check_quality(state: PolicyAgentState):
    if state.get("is_valid") or state.get("retry_count", 0) >= 2: return END
    return "agent"

workflow = StateGraph(PolicyAgentState)
workflow.add_node("agent", agent_node)
workflow.add_node("action", action_node)
workflow.add_node("grader", answer_grader)
workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent", should_continue, {"action": "action", "grader": "grader"})
workflow.add_edge("action", "agent")
workflow.add_conditional_edges("grader", check_quality, {END: END, "agent": "agent"})
app = workflow.compile()

# 8. 인터페이스 함수
async def get_AI_response(session_id, messages, user=None):
    cached_data = cache.get_cached_data(session_id) or {"messages": [], "summary": ""}
    current_summary = cached_data.get("summary", "")
    user_text = messages[-1]["content"]
    
    # 세션 관리 및 에이전트 호출 로직 
    try:
        input_data = {"messages": messages[-10:], "user_profile": {}, "summary": current_summary, "tool_calls": [], "is_valid": False, "retry_count": 0}
        result = await app.ainvoke(input_data)
        last_msg = result["messages"][-1]
        final_answer = getattr(last_msg, 'content', None) or last_msg.get('content', '')
        
        cache.set_cached_data(session_id, result["messages"], result.get("summary", current_summary))
        return final_answer
    except Exception as e:
        print(f"❌ 에러 발생 상세: {e}") 
        return "상담 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
    