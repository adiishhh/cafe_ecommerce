from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.views.decorators.http import require_POST
from decimal import Decimal
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.core.paginator import Paginator
from django.utils import timezone
from .forms import CouponForm
from .models import Coupon

# Create your views here.

ADMIN_COUPON_PAGE_SIZE = 10

def apply_coupon(coupon_code, subtotal):
    coupon_code = (coupon_code or "").strip().upper()

    if not coupon_code:
        return {
            "success": False,
            "coupon": None,
            "discount": Decimal("0.00"),
            "message": "Please enter a coupon code.",
        }

    subtotal = Decimal(subtotal)

    coupon = Coupon.objects.filter(
        code__iexact=coupon_code
    ).first()

    if coupon is None:
        return {
            "success": False,
            "coupon": None,
            "discount": Decimal("0.00"),
            "message": "Invalid coupon code.",
        }

    now = timezone.now()

    if not coupon.is_active:
        return {
            "success": False,
            "coupon": coupon,
            "discount": Decimal("0.00"),
            "message": "This coupon is no longer active.",
        }

    if now < coupon.valid_from:
        return {
            "success": False,
            "coupon": coupon,
            "discount": Decimal("0.00"),
            "message": "This coupon is not active yet.",
        }

    if now > coupon.valid_until:
        return {
            "success": False,
            "coupon": coupon,
            "discount": Decimal("0.00"),
            "message": "This coupon has expired.",
        }

    if (
        coupon.usage_limit is not None
        and coupon.used_count >= coupon.usage_limit
    ):
        return {
            "success": False,
            "coupon": coupon,
            "discount": Decimal("0.00"),
            "message": "This coupon has reached its usage limit.",
        }

    if subtotal < coupon.minimum_order_amount:
        return {
            "success": False,
            "coupon": coupon,
            "discount": Decimal("0.00"),
            "message": (
                f"This coupon requires a minimum order of "
                f"₹{coupon.minimum_order_amount:.2f}."
            ),
        }

    if coupon.discount_type == Coupon.DiscountType.PERCENTAGE:
        discount = (
            subtotal * coupon.discount_value / Decimal("100")
        )

    else:
        discount = coupon.discount_value

    if coupon.maximum_discount_amount is not None:
        discount = min(
            discount,
            coupon.maximum_discount_amount,
        )

    discount = min(
        discount,
        subtotal,
    )

    discount = discount.quantize(
        Decimal("0.01")
    )

    return {
        "success": True,
        "coupon": coupon,
        "discount": discount,
        "message": (
            f"Coupon {coupon.code} applied successfully."
        ),
    }


def _coupon_admin_check(request):

    if not request.user.is_authenticated:
        return redirect("login")

    if not request.user.is_staff:
        return HttpResponseForbidden(
            "You are not authorized to access this page."
        )

    return None


@login_required(login_url="login")
def coupon_list(request):

    forbidden = _coupon_admin_check(request)

    if forbidden:
        return forbidden

    search = request.GET.get("q", "").strip()
    discount_type_filter = request.GET.get("type", "").strip()
    status_filter = request.GET.get("status", "").strip()
    sort = request.GET.get("sort", "newest").strip()

    coupons = Coupon.objects.all()

    if search:
        coupons = coupons.filter(
            Q(code__icontains=search)
        )

    valid_discount_types = {
        choice[0]
        for choice in Coupon.DiscountType.choices
    }

    if discount_type_filter in valid_discount_types:
        coupons = coupons.filter(
            discount_type=discount_type_filter
        )

    if status_filter == "active":
        coupons = coupons.filter(
            is_active=True
        )

    elif status_filter == "inactive":
        coupons = coupons.filter(
            is_active=False
        )

    sort_options = {
        "newest": "-created_at",
        "oldest": "created_at",
        "expiry_soon": "valid_until",
        "expiry_late": "-valid_until",
        "value_high": "-discount_value",
        "value_low": "discount_value",
    }

    order_by = sort_options.get(
        sort,
        "-created_at",
    )

    coupons = coupons.order_by(
        order_by,
        "-id",
    )

    paginator = Paginator(
        coupons,
        ADMIN_COUPON_PAGE_SIZE,
    )

    page_obj = paginator.get_page(
        request.GET.get("page")
    )

    return render(
        request,
        "admin_panel/coupons.html",
        {
            "page_obj": page_obj,
            "search": search,
            "discount_type_filter": discount_type_filter,
            "status_filter": status_filter,
            "sort": sort,
            "discount_type_choices": Coupon.DiscountType.choices,
            "total_coupons": paginator.count,
        },
    )


@login_required(login_url="login")
def create_coupon(request):

    forbidden = _coupon_admin_check(request)

    if forbidden:
        return forbidden

    if request.method == "POST":

        form = CouponForm(request.POST)

        if form.is_valid():

            coupon = form.save()

            messages.success(
                request,
                f"Coupon {coupon.code} was created successfully.",
            )

            return redirect("coupon_list")

    else:

        form = CouponForm(
            initial={
                "is_active": True,
            }
        )

    return render(
        request,
        "admin_panel/coupon_form.html",
        {
            "form": form,
            "page_heading": "Create Coupon",
            "submit_text": "Create",
            "is_edit": False,
        },
    )


@login_required(login_url="login")
def edit_coupon(request, coupon_id):

    forbidden = _coupon_admin_check(request)

    if forbidden:
        return forbidden

    coupon = get_object_or_404(
        Coupon,
        id=coupon_id,
    )

    if request.method == "POST":

        form = CouponForm(
            request.POST,
            instance=coupon,
        )

        if form.is_valid():

            coupon = form.save()

            messages.success(
                request,
                f"Coupon {coupon.code} was updated successfully.",
            )

            return redirect("coupon_list")

    else:

        form = CouponForm(
            instance=coupon,
        )

    return render(
        request,
        "admin_panel/coupon_form.html",
        {
            "form": form,
            "coupon": coupon,
            "page_heading": "Edit Coupon",
            "page_description": (
                f"Update the settings for {coupon.code}."
            ),
            "submit_text": "Save Changes",
            "is_edit": True,
        },
    )


@login_required(login_url="login")
@require_POST
def toggle_coupon_status(request, coupon_id):

    forbidden = _coupon_admin_check(request)

    if forbidden:
        return forbidden

    coupon = get_object_or_404(
        Coupon,
        id=coupon_id,
    )

    coupon.is_active = not coupon.is_active

    coupon.save(
        update_fields=[
            "is_active",
            "updated_at",
        ]
    )

    if coupon.is_active:

        messages.success(
            request,
            f"Coupon {coupon.code} has been activated.",
        )

    else:

        messages.success(
            request,
            f"Coupon {coupon.code} has been deactivated.",
        )

    return redirect("coupon_list")