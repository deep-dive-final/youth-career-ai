from django.http import HttpResponse
from django.conf import settings

def set_login_cookie(response, tokens):
    """
    로그인 쿠키 세팅
    
    :param tokens: 로그인 토큰
    """
    # response = HttpResponse("login")
    set_token_cookie('ASTN', tokens["access"], response)
    set_token_cookie('RSTN', tokens["refresh"], response)

def set_token_cookie(name, token, response):
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
        secure=not settings.IS_DEV,
        samesite='Strict'
    )

def get_cookie(request, cookie_name):
    """
    쿠키 조회
    
    :param request: request
    :param cookie_name: 쿠키명
    """
    cookie_value = request.COOKIES.get(cookie_name)
    return cookie_value