from datetime import datetime, timedelta

CHAT_CACHE = {}
CACHE_TTL = timedelta(minutes=30)
MAX_MESSAGES = 6

def get_cached_messages(session_id):
    data = CHAT_CACHE.get(session_id)
    if not data:
        return None

    # TTL 체크
    if datetime.now() - data["updated_at"] > CACHE_TTL:
        CHAT_CACHE.pop(session_id, None)
        return None

    print(f"[get_cached_messages] session_id:{session_id}, messages:{data['messages']}")
    
    return data["messages"]


def set_cached_messages(session_id, messages):
    CHAT_CACHE[session_id] = {
        "messages": messages[-MAX_MESSAGES:],
        "updated_at": datetime.now()
    }

    print(f"[set_cached_messages] session_id:{session_id}, messages:{messages}")


def append_message(session_id, role, content):
    data = CHAT_CACHE.get(session_id)

    if not data:
        CHAT_CACHE[session_id] = {
            "messages": [{"role": role, "content": content}],
            "updated_at": datetime.now()
        }
        return

    data["messages"].append({"role": role, "content": content})
    data["messages"] = data["messages"][-MAX_MESSAGES:]
    data["updated_at"] = datetime.now()

    print(f"[append_message] session_id:{session_id}, role:{role}, content:{content}")
