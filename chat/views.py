from urllib import request
from bson import ObjectId
from django.shortcuts import render
from django.http import JsonResponse
import json
from django.views.decorators.csrf import csrf_exempt
import chat.utils as chat_utils
import chat.cache as chat_cache
import chat.chatbot as chatbot

# 로그인 사용자 아이디 임시 설정
USER_ID = 'test_user'

def chat(request):
    return render(request, "chat.html", {})

# 상담 창 로딩시 과거 대화 내역 불러오기
@csrf_exempt
def chat_init(request):

    # 1. 과거 대화 내역 가져오기

    try:
        return JsonResponse({"status": "success", "data": []}, json_dumps_params={'ensure_ascii': False}, safe=False)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
     
@csrf_exempt
def chat_response(request):

    body_unicode = request.body.decode('utf-8')
    body_data = json.loads(body_unicode)
    user_input = body_data.get('message') # 사용자 메세지
    
    print("[chat_response] start :", user_input)

    try:
        session_id = request.session.get("session_id") # 세션 아이디

        # 1. 세션이 없으면 세션 먼저 저장
        if not session_id:
            session_id = chat_utils.insert_session(USER_ID)
            request.session['session_id'] = session_id

        # 2. DB 저장 (user message)
        message_id = chat_utils.insert_message(session_id, 'user', user_input)

        # 2. 캐시에 user message 추가
        chat_cache.append_message(session_id, "user", user_input)

        # 3. 컨텍스트 가져오기
        messages = chat_cache.get_cached_messages(session_id)

        if messages is None:
            # 캐시 miss → DB에서 복구
            #messages = load_last_messages_from_db(session_id, limit=6)
            chat_cache.set_cached_messages(session_id, messages)

        # 4. LLM 호출
        ai_response = chatbot.get_AI_response(messages)

        # 5. DB 저장 (assistant message)
        chat_utils.insert_message(session_id, "assistant", ai_response)

        # 6. 캐시에 assistant message 추가
        chat_cache.append_message(session_id, "assistant", ai_response)

        return JsonResponse({"status": "success", "data": {"answer": ai_response}}, json_dumps_params={'ensure_ascii': False}, safe=False)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)