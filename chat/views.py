import logging
import json
import asyncio

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from asgiref.sync import sync_to_async
from bson import ObjectId
from utils.db import getMongoDbClient

import chat.utils as chat_utils
import chat.cache as chat_cache
import chat.chatbot as chatbot

logger = logging.getLogger(__name__)


def chat(request):
    return render(request, "chat.html", {})


@csrf_exempt
def chat_init(request):
    try:
        return JsonResponse(
            {"status": "success", "data": []},
            json_dumps_params={'ensure_ascii': False},
            safe=False
        )
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@csrf_exempt
async def chat_response(request):
    body_unicode = request.body.decode('utf-8')
    body_data    = json.loads(body_unicode)
    step         = body_data.get('step', 'chat')

    logger.info(f"[chat_response] step={step}")

    # 정책 상세 조회
    if step == 'detail':
        policy_id = body_data.get('policy_id', '')
        try:
            def fetch_policy():
                db = getMongoDbClient()
                try:
                    oid    = ObjectId(policy_id)
                    policy = db['policies'].find_one({"_id": oid})
                except Exception:
                    # ObjectId 변환 실패 시 문자열로 재시도
                    policy = db['policies'].find_one({"policy_id": policy_id})
                return policy

            policy = await asyncio.to_thread(fetch_policy)
            if not policy:
                return JsonResponse(
                    {"status": "error", "message": "정책 정보를 찾을 수 없습니다."},
                    status=404,
                    json_dumps_params={'ensure_ascii': False}
                )
            detail_text = chatbot.format_policy_detail(policy)
            return JsonResponse({
                "status": "success",
                "data": {"answer": detail_text, "policy_list": [], "intent": "DETAIL"}
            }, json_dumps_params={'ensure_ascii': False})

        except Exception as e:
            logger.error(f"[chat_response/detail] 에러: {e}")
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

    # 일반 대화 처리
    user_input = body_data.get('message', '')
    logger.info(f"[chat_response] user_input: {user_input[:80]}")

    try:
        # 세션 ID 조회 — 없으면 신규 생성
        def get_or_create_session():
            session_id = request.session.get("session_id")
            if not session_id:
                user_id_str = (
                    str(request.user.id)
                    if getattr(request.user, 'is_authenticated', False)
                    else "anonymous"
                )
                session_id = chat_utils.insert_session(user_id_str)
                request.session['session_id'] = session_id
                request.session.modified = True
            return session_id

        session_id = await sync_to_async(get_or_create_session)()

        # 메시지 저장 및 캐시 업데이트
        await asyncio.to_thread(chat_utils.insert_message, session_id, 'user', user_input)
        await asyncio.to_thread(chat_cache.append_message, session_id, "user", user_input)

        # 캐시에서 대화 이력 가져오기
        cached_data = await asyncio.to_thread(chat_cache.get_cached_data, session_id)
        messages    = cached_data.get("messages", []) if cached_data else []

        ai_resp = await chatbot.get_AI_response(session_id, messages, request.user)

        # 하위 호환: str 응답 → dict 변환
        if isinstance(ai_resp, str):
            ai_resp = {"answer": ai_resp, "policy_list": [], "intent": "SEARCH"}

        answer_text = ai_resp.get("answer", "")

        # 답변 텍스트만 DB·캐시에 저장
        await asyncio.to_thread(chat_utils.insert_message, session_id, "assistant", answer_text)
        await asyncio.to_thread(chat_cache.append_message, session_id, "assistant", answer_text)

        logger.info(f"[chat_response] 완료 policy_list={len(ai_resp.get('policy_list', []))}건")

        return JsonResponse({
            "status": "success",
            "data":   ai_resp,   # {answer, policy_list, intent}
        }, json_dumps_params={'ensure_ascii': False}, safe=False)

    except Exception as e:
        logger.error(f"[chat_response] 에러: {e}")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@csrf_exempt
async def reset_chat(request):
    if request.method == "POST":
        try:
            body_unicode = request.body.decode('utf-8')
            body_data    = json.loads(body_unicode)
            session_id   = body_data.get('session_id')

            if not session_id:
                def get_session():
                    return request.session.get("session_id")
                session_id = await sync_to_async(get_session)()

            if session_id:
                await asyncio.to_thread(chat_cache.set_cached_data, session_id, [], "")
                return JsonResponse(
                    {"status": "success", "message": "대화가 초기화되었습니다."},
                    json_dumps_params={'ensure_ascii': False}
                )
            else:
                return JsonResponse({"status": "error", "message": "세션 ID를 찾을 수 없습니다."}, status=400)

        except Exception as e:
            logger.error(f"[reset_chat] 에러: {e}")
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

    return JsonResponse({"status": "error", "message": "Invalid method"}, status=405)
