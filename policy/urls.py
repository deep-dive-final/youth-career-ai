from django.urls import path

from . import views

urlpatterns = [
    path("", views.policy, name="policy")
]