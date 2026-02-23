from django.urls import path

from . import views

urlpatterns = [
    path("login", views.login, name="login"),

    # Google ID Token → JWT 발급
    path("api/auth/google/", views.login_google, name="google_login"),

    # Refresh Token 블랙리스트 등록
    path("api/auth/logout/", views.logout, name="logout"),

    # 현재 사용자 정보 반환
    path("api/auth/me/", views.me, name="me"),
]