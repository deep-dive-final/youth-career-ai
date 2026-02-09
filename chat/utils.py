

from datetime import datetime

from bson import ObjectId
from utils.db import getMongoDbClient

# 처음 로딩시 과거 대화 내역 가져오기
def get_chat_history(user_id):

    chat_history = []
    # TODO: 과거 대화 내역 가져오는 로직 추가

    return chat_history

# 캐시에 메세지 없을 때 과거 대화 내역 가져와서 캐시에 저장
def get_last_messages(session_id, user_id, limit=6):
    # TODO: 과거 대화 내역 가져오는 로직 추가
    
    db = getMongoDbClient()
    chat_messages_coll = db['chat_messages']

    messages_cursor = chat_messages_coll.find(
        {"session_id": ObjectId(session_id)}
    ).sort("created_at", -1).limit(limit)

    messages = []
    for msg in messages_cursor:
        messages.append({
            "role": msg["role"],
            "content": msg["content"]
        })

    messages.reverse()  # 시간 순서대로 정렬
    return messages


# 세션 DB 저장
def insert_session(user_id):
    db = getMongoDbClient()
    chat_sessions_coll = db['chat_sessions']

    session_document ={
        "user_id": user_id,
        "started_at": datetime.now(),
        "ended_at": None, # 상담 종료 시 업데이트 필요
        "summary": "",
        "ended_reason": ""
    }

    session_insert_result = chat_sessions_coll.insert_one(session_document)
    session_id = str(session_insert_result.inserted_id)
    return session_id

# 메시지 DB 저장
def insert_message(session_id, role, content):
    db = getMongoDbClient()
    chat_messages_coll = db['chat_messages']
    message_document = {
        "session_id": ObjectId(session_id),
        "role": role,
        "content": content,
        "created_at": datetime.now()
    }

    message_insert_result = chat_messages_coll.insert_one(message_document)
    message_id = str(message_insert_result.inserted_id)
    return message_id
