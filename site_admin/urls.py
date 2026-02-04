from django.urls import path

from . import views

urlpatterns = [
    path("data", views.data, name="data"),
    path("api/importData", views.importData, name="importData"),
    path("api/getSearchData", views.getSearchData, name="getSearchData"),
]