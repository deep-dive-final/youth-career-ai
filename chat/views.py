from django.shortcuts import render
from django.http import JsonResponse
import json
from django.views.decorators.csrf import csrf_exempt
from asgiref.sync import sync_to_async  
import chat.utils as chat_utils
import chat.cache as chat_cache
import chat.chatbot as chatbot
import asyncio
from utils.db import getMongoDbClient 

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
    
    print(f"[chat_response] 시작: {user_input}")

    try:
        # 1. 세션 관리 (기존 유지)
        def get_or_create_session():
            session_id = request.session.get("session_id")
            if not session_id:
                session_id = chat_utils.insert_session(USER_ID)
                request.session['session_id'] = session_id
                request.session.modified = True 
            return session_id

        session_id = await sync_to_async(get_or_create_session)()

        # 2. 메시지 저장 및 캐시 업데이트
        await asyncio.to_thread(chat_utils.insert_message, session_id, 'user', user_input)
        await asyncio.to_thread(chat_cache.append_message, session_id, "user", user_input)

        # 3. 에이전트에게 전달할 대화 이력 가져오기
        cached_data = await asyncio.to_thread(chat_cache.get_cached_data, session_id)

        # 데이터가 있으면 그 안의 "messages" 리스트를 가져오고, 없으면 빈 리스트를 사용합니다.
        messages = cached_data.get("messages", []) if cached_data else []

        # 4. (핵심) 사용자 프로필 정보 가져오기
        # 에이전트가 맞춤형 검색(Tool Calling)을 수행
        def fetch_user_profile():
            try:
                db = getMongoDbClient()
                profile = db['user_profiles'].find_one({"user_id": USER_ID})
                if profile:
                    return {
                        "age": profile.get("age"),
                        "job": profile.get("job_status"),
                        "region": profile.get("region", "전국")
                    }
            except Exception as e:
                print(f"프로필 조회 실패: {e}")
            return {} # 실패 시 빈 딕셔너리 반환

        user_profile = await asyncio.to_thread(fetch_user_profile)

        # 5. 에이전틱 챗봇 호출 
        ai_response = await chatbot.get_AI_response(session_id, messages, request.user)

        # 6. 결과 저장
        await asyncio.to_thread(chat_utils.insert_message, session_id, "assistant", ai_response)
        await asyncio.to_thread(chat_cache.append_message, session_id, "assistant", ai_response)

        print(f"[chat_response] 완료: {ai_response}")

        return JsonResponse({
            "status": "success", 
            "data": {"answer": ai_response}
        }, json_dumps_params={'ensure_ascii': False}, safe=False)

    except Exception as e:
        print(f"Error in chat_response: {e}")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)