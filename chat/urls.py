from django.urls import path

from . import views

urlpatterns = [
    path("", views.chat, name="chat"),
    path("api/chat_init", views.chat_init, name="chat_init"),
    path("api/chat_response", views.chat_response, name="chat_response"),
]