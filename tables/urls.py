from django.urls import path
from . import views


urlpatterns = [
    path(
        "table/<str:qr_token>/",
        views.scan_table_qr,
        name="scan_table_qr"
    ),

    path(
        "admin_panel/tables/",
        views.admin_tables,
        name="admin_tables"
    ),

    path(
        "admin_panel/tables/add/",
        views.admin_add_table,
        name="admin_add_table"
    ),

    path(
        "admin_panel/tables/<int:table_id>/edit/",
        views.admin_edit_table,
        name="admin_edit_table"
    ),

    path(
        "admin_panel/tables/<int:table_id>/toggle-status/",
        views.admin_toggle_table_status,
        name="admin_toggle_table_status"
    ),

    path(
        "admin_panel/tables/<int:table_id>/qr/",
        views.admin_table_qr,
        name="admin_table_qr"
    ),

    path(
        "table/exit/",
        views.exit_table_mode,
        name="exit_table_mode"
    ),

    path(
        "guest/scan/",
        views.guest_qr_scanner,
        name="guest_qr_scanner"
    ),

]