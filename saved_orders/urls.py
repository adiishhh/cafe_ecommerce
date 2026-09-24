from django.urls import path

from . import views

urlpatterns = [
    path("my-usuals/", views.my_usuals, name="my_usuals"),
]