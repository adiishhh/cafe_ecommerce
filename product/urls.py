from django.urls import path
from . import views


urlpatterns = [
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
]