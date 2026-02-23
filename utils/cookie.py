from django.conf import settings

def set_login_cookie(response, tokens):
    """
    로그인 쿠키 세팅
    
    :param tokens: 로그인 토큰
    """
    access_cookie_name = settings.AUTH_COOKIE["ACCESS_NAME"]
    refresh_cookie_name = settings.AUTH_COOKIE["REFRESH_NAME"]
    refresh_cookie_expire = int(settings.AUTH_COOKIE["REFRESH_EXPIRE"].total_seconds())

    set_token_cookie(response, access_cookie_name, tokens["access"], refresh_cookie_expire)
    set_token_cookie(response, refresh_cookie_name, tokens["refresh"], refresh_cookie_expire)
    
def set_token_cookie(response, name, token, max_age):
    """
    Docstring for set_token_cookie
    
    :param name: 쿠키명
    :param token: 쿠키값
    :param response: Response
    """
    response.set_cookie(
        name,
        token, 
        httponly=True,
        max_age=max_age,
        secure=not settings.IS_DEV,
        samesite='Strict'
    )

def set_cookie_for_logout(response):
    access_cookie_name = settings.AUTH_COOKIE["ACCESS_NAME"]
    refresh_cookie_name = settings.AUTH_COOKIE["REFRESH_NAME"]

    set_token_cookie(response, access_cookie_name, "", -1)
    set_token_cookie(response, refresh_cookie_name, "", -1)

def get_cookie(request, cookie_name):
    """
    쿠키 조회
    
    :param request: request
    :param cookie_name: 쿠키명
    """
    cookie_value = request.COOKIES.get(cookie_name)
    return cookie_value