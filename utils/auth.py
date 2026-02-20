# accounts/auth.py
"""
JWT 인증 데코레이터 및 미들웨어.
DRF의 IsAuthenticated / JWTAuthentication을 대체.
"""
from functools import wraps
from bson import ObjectId

from .jwt import TokenError, decode_access_token
from .json import error_response
from .db import getMongoDbClient
from .cookie import get_cookie

# 인증 데코레이터
def login_required(view_func):
    """
    뷰 함수에 JWT 인증을 적용하는 데코레이터.

    사용 예시:
        @login_required
        def my_view(request):
            user = request.user  # 인증된 User 객체
            ...

    Authorization: Bearer <access_token> 헤더가 없거나 유효하지 않으면
    401 JSON 응답을 반환합니다.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        token = get_cookie(request, 'astn')
        if not token:
            return error_response('인증 토큰이 필요합니다.', status=401)

        try:
            payload = decode_access_token(token)
        except TokenError as e:
            return error_response(str(e), status=401)

        # 사용자 조회
        db = getMongoDbClient()
        users_collection = db["users"]
        user = users_collection.find_one({ "_id" : ObjectId(payload["sub"]) })

        if user == None:
            return error_response('사용자를 찾을 수 없습니다.', status=401)

        # 뷰에서 request.user 로 접근 가능
        request.user = user
        return view_func(request, *args, **kwargs)

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

def is_login(request):
    token = get_cookie(request, 'ASTN')
    if not token:
        return False

    return True