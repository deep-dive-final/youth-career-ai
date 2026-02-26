"""
JWT 인증 데코레이터 및 미들웨어.
"""
from functools import wraps
from bson import ObjectId
from django.conf import settings
from .jwt import TokenError, TokenExpiredError, decode_access_token, token_refresh, invalidate_refresh_token
from .json import error_response
from .db import getMongoDbClient
from .cookie import get_cookie, set_login_cookie
<<<<<<< Updated upstream

=======
>>>>>>> Stashed changes

def _get_valid_payload(request):
    """
    로그인 여부 체크시 인증 쿠키로부터 access token 조회
    access token 만료시 refresh token 으로 재발급 처리
    """
    try:
        # access token 복호화
        token = get_cookie(request, settings.AUTH_COOKIE["ACCESS_NAME"])

        if not token:
            return None, None
    
        return decode_access_token(token), None
    except TokenExpiredError:
        # access token 만료시 재발급 처리
        refresh_token = get_cookie(request, settings.AUTH_COOKIE["REFRESH_NAME"])
        token_refresh_result, new_token = token_refresh(refresh_token)

        if not token_refresh_result:
            return None, None

        # 재발급된 access token 복호화
        payload = decode_access_token(new_token["access"])
        return payload, new_token
    except TokenError:
        return None, None


def _set_user_from_payload(request, payload):
    """
    인증 토큰으로부터 request 에다가 사용자 정보 세팅
    """
    request.is_authenticated = True
    request.user_id = payload["sub"]
    request.email = payload["email"]
    request.user_name = payload["name"]


# 인증 데코레이터
def login_check(view_func):
    """
    로그인 여부 확인
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):

        request.is_authenticated = False
        request.user_id = None
        request.email = None
<<<<<<< Updated upstream
=======
        
        # access 토큰 확인
        token = get_cookie(request, settings.AUTH_COOKIE["ACCESS_NAME"])
        if not token:
            return view_func(request, *args, **kwargs)
        
        try:
            payload = decode_access_token(token)

            request.is_authenticated = True
            request.user_id = payload["sub"]
            request.email = payload["email"]
            
            return view_func(request, *args, **kwargs)
        except TokenExpiredError:
            # access 토큰 만료시 refresh 토큰으로 access 토큰 재발급 처리
            refresh_token = get_cookie(request, settings.AUTH_COOKIE["REFRESH_NAME"])
            token_refresh_result, new_token, message = token_refresh(refresh_token)
            print("[is_login token_refresh]", token_refresh_result, message)

            if not token_refresh_result:
                return view_func(request, *args, **kwargs)
            
            payload = decode_access_token(new_token["access"])

            request.is_authenticated = True
            request.user_id = payload["sub"]
            request.email = payload["email"]

            response = view_func(request, *args, **kwargs)
            set_login_cookie(response, new_token)
            return response
        except TokenError:
            return view_func(request, *args, **kwargs)

        #-------------------------------------------------
        # 로그인 체크시 사용자 조회까지는 안해도 될 것 같아서 주석 처리. 나중에 필요하면 주석 해제
        # 사용자 조회
        # db = getMongoDbClient()
        # users_collection = db["users"]
        # user = users_collection.find_one({ "_id" : ObjectId(payload["sub"]) })

        # if user == None:
        #     return False, 'USER DB ERROR', None
        #-------------------------------------------------
>>>>>>> Stashed changes

        # access 토큰 확인 및 만료시 재발급 처리
        payload, new_token = _get_valid_payload(request)
        if not payload:
            return view_func(request, *args, **kwargs)
        
        # request 에다가 사용자 정보 세팅
        _set_user_from_payload(request, payload)

        # access 토큰 재발급 되었으면 쿠키 세팅
        response = view_func(request, *args, **kwargs)
        if new_token:
            set_login_cookie(response, new_token)

        return response

    return wrapper


def require_methods(*methods):
    """
    허용된 HTTP 메서드만 통과시키는 데코레이터.

    사용 예시:
        @require_methods('GET', 'POST')
        def my_view(request): ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if request.method not in methods:
                return error_response(
                    f"허용되지 않는 메서드입니다. ({', '.join(methods)} 만 허용)",
                    status=405,
                )
            return view_func(request, *args, **kwargs)
        return wrapper
<<<<<<< Updated upstream
    return decorator
=======
    return decorator

def get_user_name(request):
    """
    request 에서 user_name 조회
    email 에서 @ 앞부분을 user_name 으로 사용함
    """
    user_name = '게스트'

    if request.is_authenticated and request.email != None and "@" in request.email:
        user_name = request.email.split("@")[0] 

    return user_name

>>>>>>> Stashed changes
