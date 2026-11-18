from io import BytesIO
import qrcode
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST
from .models import Table
from .forms import TableForm
from django.utils import timezone

# =========================================================
# ADMIN STAFF CHECK
# =========================================================


def admin_staff_check(request):

    if not request.user.is_staff:

        return HttpResponseForbidden("You are not authorized to access this page.")

    return None


# =========================================================
# ADMIN TABLE LIST
# =========================================================


@login_required(login_url="login")
def admin_tables(request):

    forbidden = admin_staff_check(request)

    if forbidden:
        return forbidden

    tables = Table.objects.all().order_by("table_number")

    # -----------------------------------------------------
    # SEARCH
    # -----------------------------------------------------

    search_query = request.GET.get("q", "").strip()

    if search_query:

        if search_query.isdigit():

            tables = tables.filter(table_number=int(search_query))

        else:

            tables = tables.none()

    # -----------------------------------------------------
    # SUMMARY
    # -----------------------------------------------------

    total_tables = Table.objects.count()

    active_tables = Table.objects.filter(is_active=True).count()

    inactive_tables = Table.objects.filter(is_active=False).count()

    # -----------------------------------------------------
    # PAGINATION
    # -----------------------------------------------------

    paginator = Paginator(tables, 8)

    page_number = request.GET.get("page")

    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "admin_panel/tables.html",
        {
            "page_obj": page_obj,
            "search_query": search_query,
            "total_tables": total_tables,
            "active_tables": active_tables,
            "inactive_tables": inactive_tables,
        },
    )


# =========================================================
# ADD TABLE
# =========================================================


@login_required(login_url="login")
def admin_add_table(request):

    forbidden = admin_staff_check(request)

    if forbidden:
        return forbidden

    if request.method == "POST":

        form = TableForm(request.POST)

        if form.is_valid():

            table = form.save()

            messages.success(request, f"Table {table.table_number} added successfully.")

            return redirect("admin_tables")

    else:

        form = TableForm()

    return render(
        request,
        "admin_panel/table_form.html",
        {
            "form": form,
            "page_title": "Add Table",
            "button_text": "Add Table",
        },
    )


# =========================================================
# EDIT TABLE
# =========================================================


@login_required(login_url="login")
def admin_edit_table(request, table_id):

    forbidden = admin_staff_check(request)

    if forbidden:
        return forbidden

    table = get_object_or_404(Table, id=table_id)

    if request.method == "POST":

        form = TableForm(request.POST, instance=table)

        if form.is_valid():

            form.save()

            messages.success(
                request, f"Table {table.table_number} updated successfully."
            )

            return redirect("admin_tables")

    else:

        form = TableForm(instance=table)

    return render(
        request,
        "admin_panel/table_form.html",
        {
            "form": form,
            "table": table,
            "page_title": "Edit Table",
            "button_text": "Save Changes",
        },
    )


# =========================================================
# TOGGLE TABLE STATUS
# =========================================================


@login_required(login_url="login")
@require_POST
def admin_toggle_table_status(request, table_id):

    forbidden = admin_staff_check(request)

    if forbidden:
        return forbidden

    table = get_object_or_404(Table, id=table_id)

    table.is_active = not table.is_active

    table.save(
        update_fields=[
            "is_active",
            "updated_at",
        ]
    )

    if table.is_active:

        messages.success(request, f"Table {table.table_number} activated.")

    else:

        messages.warning(request, f"Table {table.table_number} deactivated.")

    return redirect("admin_tables")


# =========================================================
# GENERATE TABLE QR CODE
# =========================================================


@login_required(login_url="login")
def admin_table_qr(request, table_id):

    forbidden = admin_staff_check(request)

    if forbidden:
        return forbidden

    table = get_object_or_404(Table, id=table_id)

    # Build the customer-facing QR URL.
    scan_url = request.build_absolute_uri(
        reverse("scan_table_qr", args=[table.qr_token])
    )

    # Generate QR image.
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )

    qr.add_data(scan_url)

    qr.make(fit=True)

    image = qr.make_image(fill_color="black", back_color="white")

    # Convert image into memory.
    buffer = BytesIO()

    image.save(buffer, format="PNG")

    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type="image/png")

    response["Content-Disposition"] = (
        f'inline; filename="table_{table.table_number}_qr.png"'
    )

    return response


def scan_table_qr(request, qr_token):

    table = get_object_or_404(Table, qr_token=qr_token)

    # Check whether the table is available.
    if not table.is_active:

        messages.warning(
            request,
            "This table is currently not available. Please contact our staff for assistance.",
        )

        return redirect("home")

    current_time = timezone.now().timestamp()

    request.session["qr_table_id"] = table.id
    request.session["qr_session_started_at"] = current_time
    request.session["qr_last_activity"] = current_time

    messages.success(
        request,
        (
            f"Welcome to Table {table.table_number}! "
            "Your table session is now active. "
            "Explore the menu and order whenever you're ready."
        ),
        extra_tags="qr-session-started",
    )

    return redirect("home")


QR_SESSION_TIMEOUT = 15 * 60  # 15 minutes


def clear_qr_session(request):
    """
    Remove only QR-related session data.
    Preserve login, cart, and other session data.
    """

    request.session.pop("qr_table_id", None)
    request.session.pop("qr_session_started_at", None)
    request.session.pop("qr_last_activity", None)

    request.session.modified = True


def get_qr_table(request, update_activity=False):

    table_id = request.session.get("qr_table_id")

    last_activity = request.session.get("qr_last_activity")

    if not table_id or not last_activity:

        clear_qr_session(request)

        return None

    current_time = timezone.now().timestamp()

    # QR session expired.
    if current_time - last_activity >= QR_SESSION_TIMEOUT:

        request.session["qr_session_expired"] = True

        clear_qr_session(request)

        return None

    table = Table.objects.filter(id=table_id, is_active=True).first()

    # Table was deactivated.
    if not table:

        request.session["qr_session_expired"] = True

        clear_qr_session(request)

        return None

    if update_activity:

        request.session["qr_last_activity"] = current_time

    return table


@require_POST
def exit_table_mode(request):

    clear_qr_session(request)

    return redirect("home")


def guest_qr_scanner(request):
    return render(request, "users_panel/guest_qr_scanner.html")
