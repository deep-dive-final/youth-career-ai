from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("api/getPolicyData", views.getPolicyData, name="getPolicyData"),
    
    path("policy/apply/", views.apply_steps, name="apply_steps"), # 신청하기 페이지(서류 작성으로 연결)
    
    path("policy/simulate/", views.simulate, name="simulate"), # 시뮬레이션 페이지

    path("policy/apply/form/", views.apply_form, name="apply_form"), # AI 신청서 페이지

    path("policy/", views.policy_detail, name='policy_detail'), #상세페이지

    path("api/get_form_fields/", views.get_form_fields, name="get_form_fields"), # 서류별 동적 입력칸 생성 API
    
    path("api/ai_generate_motivation/", views.ai_generate_motivation, name="ai_generate_motivation"), # AI 답변 생성 api

    path("policies/list/", views.policy_list, name="policy_list"), # 전체보기(정책 목록)
]