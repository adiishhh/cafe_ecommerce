from django.urls import path

from . import views

urlpatterns = [
    path(
        "my-usuals/",
        views.my_usuals,
        name="my_usuals",
    ),

    path(
        "my-usuals/create/",
        views.create_usual,
        name="create_usual",
    ),

    path(
        "my-usuals/save/",
        views.save_usual,
        name="save_usual",
    ),

    path(
        "my-usuals/<int:saved_order_id>/order-again/",
        views.order_again,
        name="order_again",
    ),

    path(
        "my-usuals/<int:saved_order_id>/edit/",
        views.edit_usual,
        name="edit_usual",
    ),

    path(
        "my-usuals/<int:saved_order_id>/delete/",
        views.delete_usual,
        name="delete_usual",
    ),
]