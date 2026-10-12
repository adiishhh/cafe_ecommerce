from django.urls import path

from . import views


urlpatterns = [
    path("wallet/", views.wallet_page, name="wallet"),
]