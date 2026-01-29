from django.urls import path

from . import views

urlpatterns = [
    path("data", views.data, name="data"),
    path("api/importData", views.importData, name="importData"),
    path("api/getDataE5", views.getDataE5, name="getDataE5"),
    path("api/getDataGemini", views.getDataGemini, name="getDataGemini")
]