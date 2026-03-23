from datetime import datetime, timedelta

CHAT_CACHE = {}
CACHE_TTL = timedelta(minutes=30)
MAX_MESSAGES = 10 

def get_cached_data(session_id):
    """메시지와 요약본을 함께 가져옴"""
    data = CHAT_CACHE.get(session_id)
    if not data:
        return None

    # TTL 체크
    if datetime.now() - data["updated_at"] > CACHE_TTL:
        CHAT_CACHE.pop(session_id, None)
        return None
    
    return data

def set_cached_data(session_id, messages, summary="", known_slots=None):
    """메시지 10개 제한 및 요약본 저장"""
    CHAT_CACHE[session_id] = {
        "messages":    messages[-MAX_MESSAGES:],
        "summary":     summary,
        "known_slots": known_slots or {},   # 대화 중 수집된 슬롯 (나이/지역/취업상태)
        "updated_at":  datetime.now()
    }

def append_message(session_id, role, content):
    data = CHAT_CACHE.get(session_id)

    if not data:
        set_cached_data(session_id, [{"role": role, "content": content}])
        return

    data["messages"].append({"role": role, "content": content})
    data["messages"] = data["messages"][-MAX_MESSAGES:]  # 10개 유지

    # Phase 1-A: user 메시지로 시작 보장 (OpenAI API 오류 방지)
    while data["messages"] and data["messages"][0]["role"] != "user":
        data["messages"].pop(0)

    data["updated_at"] = datetime.now()