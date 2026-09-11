from django.urls import path
from . import views


urlpatterns = [
    path('', views.customer_home, name='home'),
    path('products/', views.product_list, name='product_list'),
    path('products/add/', views.add_product, name='add_product'),
    path(
        'products/<int:product_id>/toggle-status/',
        views.toggle_product_status,
        name='toggle_product_status'
    ),
    path(
        'products/<int:product_id>/edit/',
        views.edit_product,
        name='edit_product'
    ),
    path(
        'products/<int:product_id>/',
        views.product_detail,
        name='product_detail'
    ),
    path(
        'menu/product/<int:product_id>/',
        views.customer_product_detail,
        name='customer_product_detail'
    ),
        path(
        'cart/',
        views.cart,
        name='cart'
    ),

    path(
        'cart/add/<int:product_id>/',
        views.add_to_cart,
        name='add_to_cart'
    ),

    path(
        'cart/increase/<int:product_id>/',
        views.increase_cart_quantity,
        name='increase_cart_quantity'
    ),

    path(
        'cart/decrease/<int:product_id>/',
        views.decrease_cart_quantity,
        name='decrease_cart_quantity'
    ),

    path(
        'cart/remove/<int:product_id>/',
        views.remove_from_cart,
        name='remove_from_cart'
    ),

]