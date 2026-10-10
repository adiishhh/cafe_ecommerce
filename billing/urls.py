from django.urls import path

from . import views


urlpatterns = [

    path(
        "admin_panel/billing/",
        views.admin_bill_list,
        name="admin_bill_list",
    ),

    path(
        "admin_panel/billing/generate/",
        views.admin_generate_bill,
        name="admin_generate_bill",
    ),

    path(
        "admin_panel/billing/<int:bill_id>/data/",
        views.admin_bill_data,
        name="admin_bill_data",
    ),

    path(
        "admin_panel/billing/<int:bill_id>/update/",
        views.admin_update_bill,
        name="admin_update_bill",
    ),
]