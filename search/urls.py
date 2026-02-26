"""
검색 앱 URL 라우팅
"""

from django.urls import path

from . import views


# ============================================================================
# URL 패턴
# ============================================================================

urlpatterns = [
    # 검색 페이지 진입
    path("", views.index, name="search"),
    # 필터 옵션 API
    path("api/filter-options", views.filter_options_api, name="filter_options_api"),
    # 검색 API
    path("api/search", views.search_policies_api, name="search_policies_api"),
]
