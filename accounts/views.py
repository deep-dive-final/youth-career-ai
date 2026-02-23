from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.conf import settings
from utils.json import json_response, error_response, parse_json_body
from utils.jwt import generate_token_pair, decode_refresh_token, generate_access_token, invalidate_refresh_token, TokenError
from utils.auth import login_check, require_methods
from utils.cookie import set_login_cookie, get_cookie, set_cookie_for_logout
from .google_auth import verify_google_id_token, get_or_create_user_from_google
from .db import get_user_by_id

@login_check
def login(request):
    print("로그인 여부:", request.is_authenticated)
    print("로그인 아이디:", request.user_id)
    return render(request, "login.html", 
                  {"GOOGLE_CLIENT_ID" : settings.GOOGLE_CLIENT_ID, 
                   "is_login" : request.is_authenticated,
                   "user_id" : request.user_id})

@csrf_exempt
def login_google(request):
    """
    POST /api/auth/google/
    Body: { "id_token": "<Google ID Token>" }

    프론트엔드에서 Google Sign-In 후 받은 id_token을 전달하면
    서버에서 Google에 검증 → 사용자 생성/조회 → JWT 반환
    """
    body_data, err = parse_json_body(request)
    if err:
        return err
    
    id_token = body_data.get('id_token')

    # 인증 토큰이 정상인지 확인
    try:
        payload = verify_google_id_token(id_token)
    except ValueError as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=401)

    # 사용자 DB 저장
    user = get_or_create_user_from_google(payload)
    if user == None:
        return JsonResponse({"status": "error", "message": "DB Error"}, status=500)
    
    # token 생성
    tokens = generate_token_pair(user)
    return_json = {"status": "success", "data": tokens}

    response = JsonResponse(return_json, json_dumps_params={'ensure_ascii': False}, safe=False)

    # 쿠키에 저장
    set_login_cookie(response, tokens)

    return response

# 로그아웃
@csrf_exempt
def logout(request):
    """
    Refresh Token을 블랙리스트에 등록해 재사용 차단.
    """
    refresh_token = get_cookie(request, settings.AUTH_COOKIE["REFRESH_NAME"])
    if refresh_token:
        invalidate_refresh_token(refresh_token)

    response = json_response({}, status=200)
    set_cookie_for_logout(response)

    return response


# 내 정보 조회
@require_methods('GET')
def me(request):
    """
    GET /api/auth/me/
    Header: Authorization: Bearer <Access Token>
    """
    return json_response(request.jwt_user, status=200)
