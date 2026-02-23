from django.shortcuts import render
from django.http import JsonResponse
import json
from django.views.decorators.csrf import csrf_exempt
from asgiref.sync import sync_to_async  # 장고 세션/DB 안전 처리를 위해 추가
import chat.utils as chat_utils
import chat.cache as chat_cache
import chat.chatbot as chatbot
import asyncio

USER_ID = 'test_user'

def chat(request):
    return render(request, "chat.html", {})

@csrf_exempt
def chat_init(request):
    try:
        return JsonResponse({"status": "success", "data": []}, json_dumps_params={'ensure_ascii': False}, safe=False)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)

@csrf_exempt
async def chat_response(request):
    body_unicode = request.body.decode('utf-8')
    body_data = json.loads(body_unicode)
    user_input = body_data.get('message')
    
    print("[chat_response] start :", user_input)

    try:
        # 1. 세션 접근을 동기 함수로 분리하여 처리
        def get_or_create_session():
            session_id = request.session.get("session_id")
            if not session_id:
                session_id = chat_utils.insert_session(USER_ID)
                request.session['session_id'] = session_id
                request.session.modified = True # 세션 변경사항 강제 저장
            return session_id

        # 2. sync_to_async를 사용하여 세션 작업 수행
        session_id = await sync_to_async(get_or_create_session)()

        # 3. DB 및 캐시 작업 (기존 방식 유지하되 안전하게 실행)
        await asyncio.to_thread(chat_utils.insert_message, session_id, 'user', user_input)
        await asyncio.to_thread(chat_cache.append_message, session_id, "user", user_input)

        messages = await asyncio.to_thread(chat_cache.get_cached_messages, session_id)

        # 4. LLM 호출 (비동기 병렬 처리의 핵심)
        ai_response = await chatbot.get_AI_response(messages)

        # 5. DB 및 캐시에 결과 저장
        await asyncio.to_thread(chat_utils.insert_message, session_id, "assistant", ai_response)
        await asyncio.to_thread(chat_cache.append_message, session_id, "assistant", ai_response)

        return JsonResponse({
            "status": "success", 
            "data": {"answer": ai_response}
        }, json_dumps_params={'ensure_ascii': False}, safe=False)

    except Exception as e:
        print(f"Error in chat_response: {e}")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)