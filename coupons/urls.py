from django.urls import path

from . import views


urlpatterns = [

    path(
        "admin_panel/coupons/",
        views.coupon_list,
        name="coupon_list",
    ),

    path(
        "admin_panel/coupons/create/",
        views.create_coupon,
        name="create_coupon",
    ),

    path(
        "admin_panel/coupons/<int:coupon_id>/edit/",
        views.edit_coupon,
        name="edit_coupon",
    ),

    path(
        "admin_panel/coupons/<int:coupon_id>/toggle/",
        views.toggle_coupon_status,
        name="toggle_coupon_status",
    ),

]