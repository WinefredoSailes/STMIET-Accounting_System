from django.urls import path

from . import views

app_name = "assistant"

urlpatterns = [
    path("chat/", views.ChatView.as_view(), name="chat"),
    path("analytics/", views.AnalyticsView.as_view(), name="analytics"),
]
