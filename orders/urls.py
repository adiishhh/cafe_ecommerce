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
]