"""
JWT 인증 데코레이터 및 미들웨어.
"""
from functools import wraps
from bson import ObjectId
from django.conf import settings
from .jwt import TokenError, TokenExpiredError, decode_access_token, token_refresh
from .json import error_response
from .db import getMongoDbClient
from .cookie import get_cookie, set_login_cookie

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