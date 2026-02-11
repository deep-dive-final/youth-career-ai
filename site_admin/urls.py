from django.urls import path

from . import views

urlpatterns = [
    path("data", views.data, name="data"),
    path("list", views.data_list, name="data_list"),
    path("api/importData", views.importData, name="importData"),
    path("api/getSearchData", views.getSearchData, name="getSearchData"),
    path("api/uploadFile", views.upload_file, name="uploadFile"),
    path("api/getKeywordData", views.get_keyword_data, name="getKeywordData"),
    path("api/setKeywordData", views.set_keyword_data, name="setKeywordData"),
]