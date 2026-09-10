from django.urls import path

from .views import APODDetailView

app_name = "apod"

urlpatterns = [
    path("apod/", APODDetailView.as_view(), name="detail"),
]
