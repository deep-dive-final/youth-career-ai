from django.urls import path

from . import views

urlpatterns = [
    path("", views.survey, name="survey"),
    path("result", views.result, name="result"),

     # 설문 결과 저장 API
    path("api/save/", views.save_survey_answers, name="save_survey_answers"),

    # 추천 API
    path("api/recommend/", views.recommend_policies, name="recommend_policies"),
]