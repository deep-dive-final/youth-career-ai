from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("api/getPolicyData", views.getPolicyData, name="getPolicyData"),
    
    path("policy/apply/", views.apply_steps, name="apply_steps"), # 신청하기 페이지(서류 작성으로 연결)
    
    path("policy/simulate/", views.simulate, name="simulate"), # 시뮬레이션 페이지

    path("policy/apply/form/", views.apply_form, name="apply_form"), # AI 신청서 페이지

    path("policy/", views.policy_detail, name='policy_detail'), #상세페이지
]