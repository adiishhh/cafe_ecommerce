from django.urls import path

from . import views


urlpatterns = [

    path(
        "wallet/",
        views.wallet_page,
        name="wallet",
    ),

    path(
        "wallet/referral/generate/",
        views.generate_referral_code,
        name="generate_referral_code",
    ),

    path(
        "wallet/referral/apply/",
        views.apply_referral_code,
        name="apply_referral_code",
    ),

]