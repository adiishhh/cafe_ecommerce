from django.shortcuts import redirect, render, get_object_or_404
from .models import Bill, BillOrder, Payment
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.utils import timezone
from datetime import datetime
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_GET
import uuid
from django.conf import settings
import razorpay
from coupons.models import Coupon
from orders.models import Order
import logging
from django.urls import reverse

# Create you views here.

logger = logging.getLogger(__name__)

def _admin_staff_check(request):

    if not request.user.is_staff:

        messages.error(
            request,
            "You do not have permission to access the admin area.",
        )

        return redirect("home")

    return None


# def _get_selected_date(request):

#     date_value = request.GET.get(
#         "date",
#         "",
#     ).strip()

#     if date_value:

#         try:

#             return timezone.datetime.strptime(
#                 date_value,
#                 "%Y-%m-%d",
#             ).date()

#         except ValueError:
#             pass

#     return timezone.localdate()


@login_required(login_url="login")
def admin_bill_list(request):
    forbidden = _admin_staff_check(request)
    if forbidden:
        return forbidden

    # ----------------------------------------------------------
    # DATE RANGE (start_date → end_date)
    # ----------------------------------------------------------
    start_date_param = request.GET.get("start_date", "").strip()
    end_date_param = request.GET.get("end_date", "").strip()

    now = timezone.localtime(timezone.now())
    today = now.date()

    try:
        start_date = datetime.strptime(start_date_param, "%Y-%m-%d").date()
    except ValueError:
        start_date = today

    try:
        end_date = datetime.strptime(end_date_param, "%Y-%m-%d").date()
    except ValueError:
        end_date = today

    if start_date > end_date:
        start_date = today
        end_date = today

    # ----------------------------------------------------------
    # ACTIVE SECTION
    # ----------------------------------------------------------
    active_view = request.GET.get("view", "unpaid_orders")
    valid_views = {"unpaid_orders", "unpaid_bills", "paid_bills", "refunds"}
    if active_view not in valid_views:
        active_view = "unpaid_orders"

    # ==========================================================
    # UNPAID ORDERS
    # ==========================================================
    unpaid_orders = (
        BillOrder.objects
        .filter(
            bill__isnull=True,
            payment_method=BillOrder.PaymentMethod.COD,
            order__status=Order.Status.DELIVERED,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
        )
        .select_related("order", "order__user")
        .prefetch_related("order__items__product")
        .order_by("-created_at", "-id")
    )

    unpaid_bills = (
        Bill.objects
        .filter(
            status=Bill.Status.UNPAID,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
        )
        .prefetch_related("bill_orders__order", "bill_orders__order__user")
        .order_by("-created_at", "-id")
    )

    paid_bills = (
        Bill.objects
        .filter(
            status=Bill.Status.PAID,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
        )
        .prefetch_related(
            "bill_orders__order",
            "bill_orders__order__user",
            "payments",
        )
        .order_by("-created_at", "-id")
    )

    refunds = (
        Payment.objects
        .filter(
            status=Payment.Status.REFUNDED,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
        )
        .select_related("bill")
        .order_by("-created_at", "-id")
    )

    return render(
        request,
        "admin_panel/bills.html",
        {
            "active_view": active_view,
            "start_date": start_date,
            "end_date": end_date,
            "start_date_value": start_date.strftime("%Y-%m-%d"),
            "end_date_value": end_date.strftime("%Y-%m-%d"),
            "unpaid_orders": unpaid_orders,
            "unpaid_bills": unpaid_bills,
            "paid_bills": paid_bills,
            "refunds": refunds,
            "total_unpaid_orders": unpaid_orders.count(),
            "total_unpaid_bills": unpaid_bills.count(),
            "total_paid_bills": paid_bills.count(),
            "total_refunds": refunds.count(),
        },
    )


@login_required(login_url="login")
@require_POST
@transaction.atomic
def admin_generate_bill(request):

    forbidden = _admin_staff_check(request)

    if forbidden:

        return JsonResponse(
            {
                "success": False,
                "message": (
                    "You do not have permission "
                    "to access the admin area."
                ),
            },
            status=403,
        )

    # ----------------------------------------------------------
    # SELECTED ORDERS
    # ----------------------------------------------------------

    selected_ids = request.POST.getlist(
        "bill_order_ids"
    )

    if not selected_ids:

        return JsonResponse(
            {
                "success": False,
                "message": "Please select at least one order.",
            },
            status=400,
        )

    # ----------------------------------------------------------
    # STATUS
    # ----------------------------------------------------------

    status = request.POST.get(
        "status",
        "unpaid",
    ).strip().lower()

    if status not in {
        "unpaid",
        "paid",
    }:

        return JsonResponse(
            {
                "success": False,
                "message": "Invalid bill status.",
            },
            status=400,
        )

    # ----------------------------------------------------------
    # TRANSACTION METHOD
    # ----------------------------------------------------------

    transaction_method = request.POST.get(
        "transaction_method",
        "",
    ).strip().lower()

    payment_reference = request.POST.get(
        "payment_reference",
        "",
    ).strip()

    if status == "paid":

        if transaction_method not in {
            "cash",
            "upi",
            "card",
        }:

            return JsonResponse(
                {
                    "success": False,
                    "message": (
                        "Please select Cash, UPI, or Card."
                    ),
                },
                status=400,
            )

        if (
            transaction_method in {"upi", "card"}
            and not payment_reference
        ):

            return JsonResponse(
                {
                    "success": False,
                    "message": (
                        "Payment reference is required "
                        "for UPI or Card."
                    ),
                },
                status=400,
            )

    else:

        transaction_method = None
        payment_reference = ""

    # ----------------------------------------------------------
    # REMOVE DUPLICATE IDS
    # ----------------------------------------------------------

    selected_ids = list(
        dict.fromkeys(selected_ids)
    )

    # ----------------------------------------------------------
    # LOCK SELECTED BILL ORDERS
    # ----------------------------------------------------------

    bill_orders = list(
        BillOrder.objects
        .select_for_update()
        .select_related(
            "order",
        )
        .filter(
            id__in=selected_ids,
        )
        .order_by(
            "id",
        )
    )

    if len(bill_orders) != len(selected_ids):

        return JsonResponse(
            {
                "success": False,
                "message": (
                    "One or more selected orders "
                    "could not be found."
                ),
            },
            status=400,
        )

    # ----------------------------------------------------------
    # VALIDATE BILL ORDERS
    # ----------------------------------------------------------

    for bill_order in bill_orders:

        if bill_order.bill_id is not None:

            return JsonResponse(
                {
                    "success": False,
                    "message": (
                        f"{bill_order.order.order_no} "
                        "has already been included in a bill."
                    ),
                },
                status=409,
            )

        if (
            bill_order.payment_method
            != BillOrder.PaymentMethod.COD
        ):

            return JsonResponse(
                {
                    "success": False,
                    "message": (
                        f"{bill_order.order.order_no} "
                        "is not a COD order."
                    ),
                },
                status=400,
            )

    # ==========================================================
    # CALCULATE BILL TOTALS
    # ==========================================================

    subtotal = sum(
        (
            bill_order.order.subtotal
            for bill_order in bill_orders
        ),
        Decimal("0.00"),
    )

    tax_amount = sum(
        (
            bill_order.order.tax_amount
            for bill_order in bill_orders
        ),
        Decimal("0.00"),
    )

    total_amount = sum(
        (
            bill_order.total
            for bill_order in bill_orders
        ),
        Decimal("0.00"),
    )

    # ==========================================================
    # CREATE BILL
    # ==========================================================

    bill = Bill.objects.create(

        subtotal=subtotal,

        tax_amount=tax_amount,

        total_amount=total_amount,

        payment_method=Bill.PaymentMethod.COD,

        transaction_method=transaction_method,

        status=(
            Bill.Status.PAID
            if status == "paid"
            else Bill.Status.UNPAID
        ),
    )

    # ==========================================================
    # ATTACH BILL ORDERS
    # ==========================================================

    for bill_order in bill_orders:

        bill_order.bill = bill

        bill_order.save(
            update_fields=[
                "bill",
            ],
        )

    # ==========================================================
    # CREATE PAYMENT ONLY WHEN BILL IS PAID
    # ==========================================================

    if status == "paid":

        Payment.objects.create(

            bill=bill,

            payment_reference=(
                payment_reference
                or None
            ),

            amount=total_amount,

            transaction_method=transaction_method,

            status=Payment.Status.SUCCESSFUL,

            gateway=None,

            gateway_payment_id=None,

            paid_at=timezone.now(),
        )

    # ==========================================================
    # AJAX RESPONSE
    # ==========================================================

    return JsonResponse(
        {
            "success": True,

            "message": (
                f"{bill.bill_no} saved successfully."
            ),

            "bill_id": bill.id,

            "bill_no": bill.bill_no,

            "status": status,

            "transaction_method": (
                transaction_method
                or ""
            ),

            "total_amount": str(
                total_amount
            ),
        }
    )

@login_required(login_url="login")
@require_GET
def admin_bill_data(request, bill_id):

    forbidden = _admin_staff_check(request)

    if forbidden:
        return JsonResponse(
            {
                "success": False,
                "message": "Permission denied."
            },
            status=403
        )


    bill = get_object_or_404(
        Bill.objects
        .prefetch_related(
            "bill_orders__order__items__product",
            "payments",
        ),
        id=bill_id,
    )


    orders = []

    for bill_order in bill.bill_orders.all():

        products = []

        for item in bill_order.order.items.all():

            products.append({
                "name": item.product.name,
                "quantity": item.quantity,
            })


        orders.append({
            "order_no": bill_order.order.order_no,
            "total": str(bill_order.total),
            "products": products,
        })


    payment = (
        bill.payments
        .filter(
            status=Payment.Status.SUCCESSFUL
        )
        .order_by("-created_at")
        .first()
    )


    return JsonResponse({
        "success": True,

        "bill": {
            "id": bill.id,
            "bill_no": bill.bill_no,

            "status": bill.status,

            "payment_method": bill.payment_method,

            "transaction_method": (
                bill.transaction_method
                if bill.transaction_method
                else (
                    payment.transaction_method
                    if payment
                    else None
                )
            ),

            "payment_reference": (
                payment.payment_reference
                if payment
                else ""
            ),

            "subtotal": str(bill.subtotal),
            "tax_amount": str(bill.tax_amount),
            "total_amount": str(bill.total_amount),

            "orders": orders,
        }
    })

@login_required(login_url="login")
@require_POST
@transaction.atomic
def admin_update_bill(request, bill_id):

    forbidden = _admin_staff_check(request)

    if forbidden:
        return JsonResponse(
            {
                "success": False,
                "message": "Permission denied."
            },
            status=403
        )


    bill = get_object_or_404(
        Bill.objects.select_for_update(),
        id=bill_id,
    )


    status = request.POST.get("status", "").strip()

    transaction_method = (
        request.POST.get(
            "transaction_method",
            ""
        ).strip()
    )

    payment_reference = (
        request.POST.get(
            "payment_reference",
            ""
        ).strip()
    )


    if status not in {
        Bill.Status.UNPAID,
        Bill.Status.PAID,
    }:

        return JsonResponse(
            {
                "success": False,
                "message": "Invalid bill status."
            },
            status=400
        )


    valid_methods = {
        Bill.TransactionMethod.CASH,
        Bill.TransactionMethod.UPI,
        Bill.TransactionMethod.CARD,
    }


    if status == Bill.Status.PAID:

        if transaction_method not in valid_methods:

            return JsonResponse(
                {
                    "success": False,
                    "message": (
                        "Please select a transaction method."
                    )
                },
                status=400
            )


        if (
            transaction_method
            in {
                Bill.TransactionMethod.UPI,
                Bill.TransactionMethod.CARD,
            }
            and not payment_reference
        ):

            return JsonResponse(
                {
                    "success": False,
                    "message": (
                        "Payment reference is required "
                        "for UPI or Card."
                    )
                },
                status=400
            )


    # ---------------------------------------------------------
    # Prevent silently reversing an already completed payment.
    # ---------------------------------------------------------

    existing_successful_payment = (
        Payment.objects
        .filter(
            bill=bill,
            status=Payment.Status.SUCCESSFUL,
        )
        .first()
    )


    if (
        bill.status == Bill.Status.PAID
        and status == Bill.Status.UNPAID
        and existing_successful_payment
    ):

        return JsonResponse(
            {
                "success": False,
                "message": (
                    "This bill already has a successful "
                    "payment. Use the refund workflow instead "
                    "of changing it back to unpaid."
                )
            },
            status=400
        )


    bill.status = status


    if status == Bill.Status.UNPAID:

        bill.transaction_method = None

        bill.save(
            update_fields=[
                "status",
                "transaction_method",
                "updated_at",
            ]
        )

    else:

        bill.transaction_method = (
            transaction_method
        )

        bill.save(
            update_fields=[
                "status",
                "transaction_method",
                "updated_at",
            ]
        )


        payment = (
            Payment.objects
            .filter(
                bill=bill,
                status=Payment.Status.SUCCESSFUL,
            )
            .order_by("-created_at")
            .first()
        )


        if payment:

            payment.transaction_method = (
                transaction_method
            )

            payment.payment_reference = (
                payment_reference or None
            )

            payment.amount = bill.total_amount

            payment.save(
                update_fields=[
                    "transaction_method",
                    "payment_reference",
                    "amount",
                ]
            )

        else:

            Payment.objects.create(
                bill=bill,
                payment_reference=(
                    payment_reference or None
                ),
                amount=bill.total_amount,
                transaction_method=(
                    transaction_method
                ),
                status=Payment.Status.SUCCESSFUL,
                gateway=None,
                gateway_payment_id=None,
                paid_at=timezone.now(),
            )


    return JsonResponse({
        "success": True,

        "message": "Bill updated successfully.",

        "bill": {
            "id": bill.id,
            "bill_no": bill.bill_no,
            "status": bill.status,
            "transaction_method": (
                bill.transaction_method
                or None
            ),
        }
    })

def _razorpay_client():
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        raise ValueError(
            "Razorpay API credentials are not configured."
        )

    return razorpay.Client(
        auth=(
            settings.RAZORPAY_KEY_ID,
            settings.RAZORPAY_KEY_SECRET,
        )
    )


def _get_online_checkout(request):
    """
    Return a server-calculated checkout snapshot.

    The snapshot is retained in the Django session while the
    customer completes the external payment.
    """

    from orders.views import _get_checkout_cart, Order

    from coupons.views import apply_coupon

    checkout = _get_checkout_cart(request)

    if checkout is None:
        raise ValueError("Your cart is empty.")

    order_type = request.session.get("checkout_order_type")

    if order_type not in {
        Order.OrderType.PICKUP,
        Order.OrderType.DELIVERY,
    }:
        raise ValueError("Please select a valid order type.")

    address_data = None

    if order_type == Order.OrderType.DELIVERY:
        address_id = request.session.get("checkout_address_id")

        if not address_id:
            raise ValueError("Please select a delivery address.")

        address = (
            request.user.addresses
            .filter(id=address_id)
            .first()
        )

        if address is None:
            raise ValueError(
                "The selected delivery address is unavailable."
            )

        address_data = {
            "name": address.name,
            "contact_number": address.contact_number,
            "flat_house": address.flat_house,
            "area_street": address.area_street,
            "city": address.city,
            "state": address.state,
            "pincode": address.pincode,
        }

    coupon = None
    discount = Decimal("0.00")

    coupon_code = request.session.get(
        "checkout_coupon_code",
        "",
    )

    if coupon_code:
        result = apply_coupon(
            coupon_code,
            checkout["subtotal"],
        )

        if result["success"]:
            coupon = result["coupon"]
            discount = result["discount"]

    subtotal = checkout["subtotal"]
    tax_amount = checkout["gst"]
    tax_percentage = checkout["tax_percentage"]

    total = (
        subtotal
        + tax_amount
        - discount
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    if total <= Decimal("0.00"):
        raise ValueError(
            "The checkout total must be greater than zero."
        )

    cart_items = []

    for item in checkout["cart_items"]:
        cart_items.append({
            "product_id": item["product"].id,
            "quantity": item["quantity"],
            "instructions": item["instructions"],
            "unit_price": str(item["product"].price),
            "item_total": str(item["item_total"]),
        })

    coupon_data = None

    if coupon:
        coupon_data = {
            "id": coupon.id,
            "code": coupon.code,
            "discount_type": getattr(
                coupon,
                "discount_type",
                "",
            ),
            "discount_value": str(
                getattr(
                    coupon,
                    "discount_value",
                    Decimal("0.00"),
                )
            ),
            "minimum_order_amount": str(
                getattr(
                    coupon,
                    "minimum_order_amount",
                    Decimal("0.00"),
                )
            ),
            "maximum_discount_amount": str(
                getattr(
                    coupon,
                    "maximum_discount_amount",
                    Decimal("0.00"),
                )
            ),
        }

    return {
        "user_id": request.user.id,
        "order_type": order_type,
        "address": address_data,
        "cart_items": cart_items,
        "subtotal": str(subtotal),
        "tax_amount": str(tax_amount),
        "tax_percentage": str(tax_percentage),
        "discount": str(discount),
        "total": str(total),
        "coupon": coupon_data,
    }


@login_required(login_url="login")
@require_POST
def initiate_online_payment(request):
    """
    Create a Razorpay order and display the Razorpay checkout page.

    No SmartCafe Order is created at this stage.
    """

    try:
        client = _razorpay_client()
        snapshot = _get_online_checkout(request)

        amount_paise = int(
            (
                Decimal(snapshot["total"])
                * Decimal("100")
            ).quantize(
                Decimal("1"),
                rounding=ROUND_HALF_UP,
            )
        )

        gateway_order = client.order.create({
            "amount": amount_paise,
            "currency": "INR",
            "receipt": (
                f"sc_{request.user.id}_"
                f"{uuid.uuid4().hex[:20]}"
            ),
            "notes": {
                "customer_id": str(request.user.id),
                "order_type": snapshot["order_type"],
            },
        })

        snapshot["gateway_order_id"] = gateway_order["id"]
        snapshot["amount_paise"] = amount_paise

        request.session["razorpay_pending_checkout"] = snapshot
        request.session.modified = True

        return render(
            request,
            "users_panel/razorpay_checkout.html",
            {
                "razorpay_key_id": settings.RAZORPAY_KEY_ID,
                "gateway_order_id": gateway_order["id"],
                "amount_paise": amount_paise,
                "total": snapshot["total"],
                "customer_name": request.user.name,
                "customer_email": request.user.email,
                "customer_phone": request.user.phone,
            },
        )

    except ValueError as exc:
        logger.warning(
            "Online checkout validation failed: %s",
            exc,
        )

        request.session.pop(
            "razorpay_pending_checkout",
            None,
        )

        messages.error(request, str(exc))

        return redirect("final_checkout")

    except Exception:
        logger.exception(
            "Failed to initiate Razorpay payment."
        )

        messages.error(
            request,
            "We could not start online payment. "
            "Please try again or choose Cash on Delivery.",
        )

        return redirect("final_checkout")


@login_required(login_url="login")
@require_POST
def verify_online_payment(request):
    """
    Verify the Razorpay callback and create the SmartCafe order.

    The gateway order ID is trusted only when it matches the
    server-created ID retained in the user's session.
    """

    from orders.models import Order, OrderItem
    from orders.views import _generate_order_number
    from product.models import Product

    payment_id = request.POST.get(
        "razorpay_payment_id",
        "",
    ).strip()

    gateway_order_id = request.POST.get(
        "razorpay_order_id",
        "",
    ).strip()

    signature = request.POST.get(
        "razorpay_signature",
        "",
    ).strip()

    if not payment_id or not gateway_order_id or not signature:
        return JsonResponse(
            {
                "success": False,
                "message": "The payment response is incomplete.",
            },
            status=400,
        )

    # An already-recorded successful callback must not create
    # another order.
    existing_payment = (
        Payment.objects
        .filter(gateway_payment_id=payment_id)
        .select_related("bill")
        .first()
    )

    if existing_payment:
        existing_bill_order = (
            BillOrder.objects
            .filter(bill=existing_payment.bill)
            .select_related("order")
            .first()
        )

        if (
            existing_payment.status == Payment.Status.SUCCESSFUL
            and existing_bill_order
            and existing_bill_order.order.user_id == request.user.id
        ):
            return JsonResponse({
                "success": True,
                "redirect_url": (
                    reverse(
                        "order_detail",
                        args=[existing_bill_order.order.id],
                    )
                ),
            })

        return JsonResponse(
            {
                "success": False,
                "message": "This payment has already been processed.",
            },
            status=409,
        )

    snapshot = request.session.get(
        "razorpay_pending_checkout"
    )

    if not snapshot:
        return JsonResponse(
            {
                "success": False,
                "message": (
                    "The pending checkout has expired. "
                    "Please return to checkout."
                ),
            },
            status=400,
        )

    if snapshot.get("user_id") != request.user.id:
        return JsonResponse(
            {
                "success": False,
                "message": "The checkout does not belong to this user.",
            },
            status=403,
        )

    trusted_order_id = snapshot.get("gateway_order_id")

    if gateway_order_id != trusted_order_id:
        return JsonResponse(
            {
                "success": False,
                "message": "The payment order ID does not match.",
            },
            status=400,
        )

    try:
        client = _razorpay_client()

        # Verify using the server-held gateway order ID.
        client.utility.verify_payment_signature({
            "razorpay_order_id": trusted_order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        })

        # Fetch authoritative payment information from Razorpay.
        gateway_payment = client.payment.fetch(payment_id)

        if gateway_payment["order_id"] != trusted_order_id:
            raise ValueError(
                "The payment is associated with a different gateway order."
            )

        if gateway_payment["status"] != "captured":
            raise ValueError(
                "The payment has not been captured yet."
            )

        if int(gateway_payment["amount"]) != int(
            snapshot["amount_paise"]
        ):
            raise ValueError(
                "The captured amount does not match the checkout total."
            )

        if gateway_payment["currency"] != "INR":
            raise ValueError(
                "The payment currency is not supported."
            )

        gateway_method = gateway_payment.get("method", "")

        method_map = {
            "upi": Payment.TransactionMethod.UPI,
            "card": Payment.TransactionMethod.CARD,
        }

        transaction_method = method_map.get(gateway_method)

        if transaction_method is None:
            raise ValueError(
                "This payment method is not supported by SmartCafe."
            )

        address_data = snapshot.get("address") or {}

        subtotal = Decimal(snapshot["subtotal"])
        tax_amount = Decimal(snapshot["tax_amount"])
        tax_percentage = Decimal(snapshot["tax_percentage"])
        discount = Decimal(snapshot["discount"])
        total = Decimal(snapshot["total"])

        with transaction.atomic():
            # Lock against simultaneous processing of the same
            # gateway payment.
            if Payment.objects.select_for_update().filter(
                gateway_payment_id=payment_id,
            ).exists():
                raise ValueError(
                    "This payment has already been processed."
                )

            coupon_data = snapshot.get("coupon") or {}

            order = Order.objects.create(
                user=request.user,
                order_no=_generate_order_number(),
                tracking_no=None,
                order_type=snapshot["order_type"],
                table=None,

                address_name=address_data.get("name"),
                address_contact_number=address_data.get(
                    "contact_number"
                ),
                address_flat_house=address_data.get("flat_house"),
                address_area_street=address_data.get("area_street"),
                address_city=address_data.get("city"),
                address_state=address_data.get("state"),
                address_pincode=address_data.get("pincode"),

                coupon_code=coupon_data.get("code", ""),

                coupon_discount_type=(coupon_data.get("discount_type") or ""),
                coupon_discount_value=(
                    Decimal(coupon_data["discount_value"])
                    if coupon_data.get("discount_value") is not None
                    else None
                ),
                coupon_minimum_order_amount=(
                    Decimal(coupon_data["minimum_order_amount"])
                    if coupon_data.get("minimum_order_amount") is not None
                    else None
                ),
                coupon_maximum_discount_amount=(
                    Decimal(coupon_data["maximum_discount_amount"])
                    if coupon_data.get("maximum_discount_amount") is not None
                    else None
                ),

                status=Order.Status.CONFIRMED,
                subtotal=subtotal,
                tax_percentage=tax_percentage,
                tax_amount=tax_amount,
                discount_amount=discount,
                total_amount=total,
            )

            for item_data in snapshot["cart_items"]:
                product = Product.objects.get(
                    id=item_data["product_id"],
                )

                OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=item_data["quantity"],
                    unit_price=Decimal(item_data["unit_price"]),
                    instructions=item_data["instructions"],
                    subtotal=Decimal(item_data["item_total"]),
                )

            bill = Bill.objects.create(
                subtotal=subtotal - discount,
                tax_amount=tax_amount,
                total_amount=total,
                payment_method=Bill.PaymentMethod.ONLINE,
                transaction_method=transaction_method,
                status=Bill.Status.PAID,
                issued_at=timezone.now(),
            )

            BillOrder.objects.create(
                order=order,
                bill=bill,
                total=total,
                payment_method=BillOrder.PaymentMethod.ONLINE,
            )

            Payment.objects.create(
                bill=bill,
                transaction_method=transaction_method,
                amount=total,
                payment_reference=payment_id,
                status=Payment.Status.SUCCESSFUL,
                gateway="razorpay",
                gateway_order_id=trusted_order_id,
                gateway_payment_id=payment_id,
                paid_at=timezone.now(),
            )

            coupon_data = snapshot.get("coupon")
            if coupon_data:
                coupon = (
                    Coupon.objects
                    .select_for_update()
                    .filter(id=coupon_data["id"])
                    .first()
                )

                if coupon:
                    coupon.used_count += 1

                    coupon.save(
                        update_fields=[
                            "used_count",
                            "updated_at",
                        ]
                    )

            request.session.pop("cart", None)
            request.session.pop("checkout_order_type", None)
            request.session.pop("checkout_address_id", None)
            request.session.pop("checkout_address_modal", None)
            request.session.pop("checkout_coupon_code", None)
            request.session.pop("razorpay_pending_checkout", None)

            request.session["last_order_payment_method"] = (
                f"Online - {gateway_method.upper()}"
            )

            request.session.modified = True

        return JsonResponse({
            "success": True,
            "redirect_url": reverse(
                "order_detail",
                args=[order.id],
            ),
        })

    except razorpay.errors.SignatureVerificationError:
        return JsonResponse(
            {
                "success": False,
                "message": "Payment verification failed.",
            },
            status=400,
        )

    except Exception:
        logger.exception(
            "Unexpected error during Razorpay payment processing."
        )

@login_required(login_url="login")
def download_invoice(request, order_id):
    order = get_object_or_404(
        Order.objects
        .select_related("user")
        .prefetch_related(
            "items__product",
        ),
        id=order_id,
        user=request.user,
    )

    bill_order = getattr(
        order,
        "bill_order",
        None,
    )

    bill = bill_order.bill if bill_order else None

    payment = None

    if bill:
        payment = (
            bill.payments
            .filter(
                status="successful",
            )
            .order_by("-created_at")
            .first()
        )

    return render(
        request,
        "users_panel/invoice.html",
        {
            "order": order,
            "bill_order": bill_order,
            "bill": bill,
            "payment": payment,
            "payment_method": (
                bill.get_transaction_method_display()
                if bill and bill.transaction_method
                else (
                    bill_order.get_payment_method_display()
                    if bill_order
                    else "—"
                )
            ),
        },
    )