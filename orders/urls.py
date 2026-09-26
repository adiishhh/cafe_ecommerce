from django.urls import path
from . import views


urlpatterns = [
    path("order/type/", views.order_type, name="order_type"),
    path(
        "order/type/address/",
        views.select_checkout_address,
        name="select_checkout_address",
    ),
    path(
        "order/checkout/",
        views.final_checkout,
        name="final_checkout",
    ),
    path(
        "order/place/",
        views.place_order,
        name="place_order",
    ),
    path(
        "order/<int:order_id>/detail/",
        views.order_detail,
        name="order_detail",
    ),
    path(
        "order/<int:order_id>/cancel/",
        views.cancel_order,
        name="cancel_order",
    ),
    path(
        "order/item/<int:item_id>/cancel/",
        views.cancel_order_item,
        name="cancel_order_item",
    ),
    path(
        "order/<int:order_id>/invoice/",
        views.download_invoice,
        name="download_invoice",
    ),
    path(
        "placed_orders",
        views.placed_orders,
        name="placed_orders",
    ),
    path(
        "admin_panel/orders/",
        views.admin_order_list,
        name="admin_order_list",
    ),
    path(
        "admin_panel/orders/<int:order_id>/",
        views.admin_order_detail,
        name="admin_order_detail",
    ),
    path(
        "admin_panel/orders/<int:order_id>/status/",
        views.admin_update_order_status,
        name="admin_update_order_status",
    ),
]