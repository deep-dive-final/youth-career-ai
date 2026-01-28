from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("api/getPolicyData", views.getPolicyData, name="getPolicyData"),
    
    path("policy/apply/", views.apply_steps, name="apply_steps"),
    
    path("policy/simulate/", views.simulate, name="simulate"),
]