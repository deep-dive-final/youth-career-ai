from django.urls import path

from . import views

urlpatterns = [
    path("", views.data_list, name="site_admin_home"),
    path("data", views.data, name="data"),
    path("list", views.data_list, name="data_list"),
    path("api/importData", views.importData, name="importData"),
    path("api/getSearchData", views.getSearchData, name="getSearchData"),
    path("api/uploadFile", views.upload_file, name="uploadFile"),
    path("api/getKeywordData", views.get_keyword_data, name="getKeywordData"),
    path("api/setKeywordData", views.set_keyword_data, name="setKeywordData"),
    path("chart", views.chart, name="chart"),
    path("api/chart/getData", views.get_data_for_chart, name="getChartData"),
    path("api/chart/getArrayData", views.get_arr_data_for_chart, name="getArrayChartData"),
    path("labeling/", views.labeling, name="labeling"),
    path("api/labeling/delete-label/", views.delete_label, name="delete_label"),
    path("summary-cache/", views.summary_cache_page, name="summary_cache_page"),
    path("api/summary-cache/list/", views.get_summary_cache_list, name="summary_cache_list"),
    path("api/summary-cache/update/", views.update_summary_cache, name="summary_cache_update"),
]