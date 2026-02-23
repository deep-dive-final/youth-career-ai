# PyJWT를 이용한 JWT 발급 / 검증 유틸리티
import uuid
from datetime import datetime, timezone, timedelta

import jwt
from django.conf import settings
from accounts.db import get_user_by_id
from .db import getMongoDbClient

SECRET = settings.SECRET_KEY
ALGORITHM = 'HS256'
ACCESS_EXPIRE  = settings.AUTH_COOKIE["ACCESS_EXPIRE"]
REFRESH_EXPIRE = settings.AUTH_COOKIE["REFRESH_EXPIRE"]

# 토큰 생성
def _build_payload(user, token_type: str, lifetime: timedelta) -> dict:
    now = datetime.now(tz=timezone.utc)
    return {
        'sub': str(user["_id"]), # subject: 사용자 PK
        'email': user["email"],
        'type': token_type, # 'access' | 'refresh'
        'jti': str(uuid.uuid4()), # JWT ID (블랙리스트용)
        'iat': now, # issued at
        'exp': now + lifetime, # expiry
    }

def generate_access_token(user) -> str:
    payload = _build_payload(user, 'access', ACCESS_EXPIRE)
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)

def generate_refresh_token(user) -> str:
    payload = _build_payload(user, 'refresh', REFRESH_EXPIRE)
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)

def generate_token_pair(user) -> dict:
    """Access + Refresh 토큰 쌍 반환"""
    return {
        'access':  generate_access_token(user),
        'refresh': generate_refresh_token(user),
    }

# 토큰 검증
class TokenError(Exception):
    """JWT 검증 실패 시 발생"""
    pass

class TokenExpiredError(TokenError):
    """토큰 만료 시 발생"""
    pass

def decode_token(token: str, expected_type: str | None = None) -> dict:
    """
    토큰 디코딩 및 검증.
    실패 시 TokenError 발생.
    """
    try:
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError('토큰이 만료되었습니다.')
    except jwt.InvalidTokenError as e:
        raise TokenError(f'유효하지 않은 토큰입니다: {e}')

    if expected_type and payload.get('type') != expected_type:
        raise TokenError(f"'{expected_type}' 타입 토큰이 필요합니다.")

    return payload

def decode_access_token(token: str) -> dict:
    return decode_token(token, expected_type='access')

def decode_refresh_token(token: str) -> dict:
    payload = decode_token(token, expected_type='refresh')

    # 블랙리스트 확인 (로그아웃된 토큰)
    db = getMongoDbClient()
    invalidated_token = db['invalidated_token']
    token_exist_count = invalidated_token.count_documents({"jti":payload.get('jti')})

    if token_exist_count > 0:
        raise TokenError('이미 무효화된 토큰입니다.')

    return payload

# 블랙리스트
def invalidate_refresh_token(token: str) -> None:
    """
    Refresh Token을 블랙리스트에 등록 (로그아웃).
    이미 만료/무효인 토큰도 예외 없이 처리.
    """
    try:
        payload = decode_token(token, expected_type='refresh')
    except TokenError:
        return  # 이미 무효 → 무시

    expired_at = datetime.fromtimestamp(payload['exp'], tz=timezone.utc)

    db = getMongoDbClient()
    invalidated_token = db['invalidated_token']
    invalidated_token.insert_one({
        "user_id" : payload["sub"],
        "jti" : payload["jti"],
        "expired_at" : expired_at
    })

def token_refresh(refresh_token):
    """
    유효한 Refresh Token으로 새 Access Token 발급
    """
    # refresh 토큰 복호화
    try:
        payload = decode_refresh_token(refresh_token)
    except TokenError as e:
        return False, None, 'REFRESH TOKEN ERROR'

    # 사용자 조회
    try:
        user = get_user_by_id(payload['sub'])
    except Exception as e:
        return False, None, 'USER DB ERROR'

    # 새로운 토큰 발급
    invalidate_refresh_token(refresh_token)
    new_access_token = generate_access_token(user)
    new_refresh_token = generate_refresh_token(user)

    token = {"access" : new_access_token,
             "refresh" : new_refresh_token}
    
    return True, token, 'SUCCESS'
