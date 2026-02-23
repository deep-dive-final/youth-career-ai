# Google ID Token 검증 및 사용자 생성/조회 유틸리티.
import requests
from django.conf import settings
from .db import get_user_by_email, update_user_last_login, insert_user

GOOGLE_TOKEN_INFO_URL = 'https://oauth2.googleapis.com/tokeninfo'
LOGIN_PROVIDER = 'google'

def verify_google_id_token(id_token: str) -> dict:
    """
    Google ID Token을 Google 서버에 검증 요청.
    성공 시 payload dict 반환, 실패 시 GoogleAuthError 발생.

    payload 주요 필드:
        sub, email, email_verified, name, given_name, family_name, picture
    """
    try:
        response = requests.get(
            GOOGLE_TOKEN_INFO_URL,
            params={'id_token': id_token},
            timeout=5,
        )
    except requests.RequestException as e:
        raise ConnectionError(f'Google 서버 연결 실패: {e}')
    
    if response.status_code != 200:
        raise ValueError('유효하지 않은 Google ID Token입니다.')

    payload = response.json()

    # 이 앱을 위한 토큰인지 확인 (audience 검증)
    if payload.get('aud') != settings.GOOGLE_CLIENT_ID:
        raise ValueError('Token audience가 일치하지 않습니다.')

    return payload

def get_or_create_user_from_google(payload: dict) -> dict:
    """
    Google payload로 User를 조회하거나 신규 생성.
    반환: (user, created: bool)
    """
    email = payload['email']
    provider = "google"

    # 기존에 저장된 유저인지 확인
    exist_user = get_user_by_email(email, provider)

    if exist_user:
        # 기존에 저장된 유저이면 update
        user_id = update_user_last_login(exist_user["_id"])
    else:
        # 신규 유저이면 insert
        user_id = insert_user(email, provider)

    if user_id:
        user_info = {
            "_id" : user_id,
            "email" : email
        }
    else:
        user_info = None

    return user_info
