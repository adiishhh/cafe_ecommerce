from django.urls import path
from . import views


urlpatterns = [
    path('categories/', views.category_list, name='category_list'), 
    path('categories/add/', views.add_category, name='add_category'),
    path(
        'categories/<int:category_id>/edit/',
        views.edit_category,
        name='edit_category'
    ),

    path(
        'categories/<int:category_id>/toggle/',
        views.toggle_category_status,
        name='toggle_category_status'
    ),
]