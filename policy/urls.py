from django.urls import path

from . import views

urlpatterns = [
    path("", views.policy, name="policy"),

    # ✅ 추가: /policy/detail/
    path("detail/", views.policy_detail_page, name="policy_detail_page"),
]