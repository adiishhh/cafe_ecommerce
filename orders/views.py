from django.shortcuts import render, redirect, get_object_or_404
from decimal import Decimal
from django.contrib.auth.decorators import login_required
from product.models import Product
import random
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.views.decorators.http import require_POST
from product.models import Product
from users.models import Address
from .models import Order, OrderItem, Tax
from django.http import HttpResponse, JsonResponse
from django.conf import settings
from django.db.models import Q, Count, Sum
from django.utils import timezone
from datetime import timedelta, datetime
from django.core.paginator import Paginator
from coupons.views import apply_coupon
from billing.models import Bill, BillOrder, Payment, RefundRequest
from wallet.models import WalletTransaction
from wallet.views import reward_referral_for_order, debit_wallet, get_customer_wallet

# Create your views here.

MAX_CART_QUANTITY = 10
ADMIN_ORDER_PAGE_SIZE = 10

def _get_current_tax():
    tax = Tax.objects.first()

    if tax is None:
        tax = Tax.objects.create(
            percentage=Decimal("5.00")
        )

    return tax

def _get_cart_item(cart, product_id):
    item = cart.get(str(product_id))

    if item is None:
        return None

    if isinstance(item, int):
        return {
            "quantity": item,
            "instructions": "",
        }

    return {
        "quantity": int(item.get("quantity", 0)),
        "instructions": item.get(
            "instructions",
            ""
        ).strip(),
    }


def _get_checkout_cart(request):
    session_cart = request.session.get(
        "cart",
        {}
    )

    if not session_cart:
        return None

    products = Product.objects.select_related(
        "category"
    ).prefetch_related(
        "images"
    ).filter(
        id__in=session_cart.keys()
    )

    cart_items = []

    subtotal = Decimal("0.00")
    cart_count = 0

    for product in products:

        item = _get_cart_item(
            session_cart,
            product.id
        )

        if not item:
            continue

        quantity = item["quantity"]

        if quantity < 1:
            continue

        quantity = min(
            quantity,
            MAX_CART_QUANTITY
        )

        is_available = (
            product.is_active and product.category.is_active
        )

        if not is_available:
            continue

        item_total = (
            product.price * quantity
        )

        subtotal += item_total
        cart_count += quantity

        cart_items.append(
            {
                "product": product,
                "quantity": quantity,
                "instructions": item["instructions"],
                "item_total": item_total,
            }
        )

    if not cart_items:
        return None

    tax = _get_current_tax()
    tax_percentage = tax.percentage

    tax_rate = tax_percentage / Decimal("100")

    gst = (
        subtotal * tax_rate
    ).quantize(
        Decimal("0.01")
    )

    total = subtotal + gst

    return {
        "cart_items": cart_items,
        "cart_count": cart_count,
        "subtotal": subtotal,
        "gst": gst,
        "tax_percentage": tax_percentage,
        "shipping": Decimal("0.00"),
        "discount": Decimal("0.00"),
        "total": total,
    }


def _generate_order_number():

    while True:

        number = random.randint(
            1000,
            9999
        )

        order_no = f"ORD-{number}"

        if not Order.objects.filter(
            order_no=order_no
        ).exists():

            return order_no


@login_required(login_url="login")
def order_type(request):

    checkout = _get_checkout_cart(request)

    if checkout is None:

        messages.info(
            request,
            "Your order is empty."
        )

        return redirect("cart")

    if request.method == "POST":

        selected_type = request.POST.get(
            "order_type"
        )

        if selected_type not in {
            Order.OrderType.PICKUP,
            Order.OrderType.DELIVERY,
        }:

            messages.error(
                request,
                "Please choose a valid order type."
            )

            return redirect("order_type")

        request.session[
            "checkout_order_type"
        ] = selected_type

        if selected_type == Order.OrderType.PICKUP:

            request.session.pop(
                "checkout_address_id",
                None
            )

            request.session.pop(
                "checkout_address_modal",
                None
            )

            request.session.modified = True

            return redirect("final_checkout")

        request.session.pop(
            "checkout_address_modal",
            None
        )

        request.session.modified = True

    selected_type = request.session.get(
        "checkout_order_type"
    )

    selected_address = None

    if selected_type == Order.OrderType.DELIVERY:

        address_id = request.session.get(
            "checkout_address_id"
        )

        if address_id:

            selected_address = (
                request.user.addresses
                .filter(id=address_id)
                .first()
            )

        if selected_address is None:

            selected_address = (
                request.user.addresses
                .filter(is_default=True)
                .first()
            )

            if selected_address:

                request.session[
                    "checkout_address_id"
                ] = selected_address.id

                request.session.modified = True

    addresses = (
        request.user.addresses
        .all()
        .order_by(
            "-is_default",
            "-id"
        )
    )

    address_modal = False

    return render(
        request,
        "users_panel/order_type.html",
        {
            **checkout,
            "selected_order_type": selected_type,
            "selected_address": selected_address,
            "addresses": addresses,
            "address_modal": address_modal,
        }
    )


@login_required(login_url="login")
@require_POST
def select_checkout_address(request):

    address_id = request.POST.get(
        "address_id"
    )

    address = get_object_or_404(
        request.user.addresses,
        id=address_id
    )

    request.session[
        "checkout_order_type"
    ] = Order.OrderType.DELIVERY

    request.session[
        "checkout_address_id"
    ] = address.id

    request.session[
        "checkout_address_modal"
    ] = False

    request.session.modified = True

    return redirect(
        "final_checkout"
    )


@login_required(login_url="login")
def final_checkout(request):

    checkout = _get_checkout_cart(request)

    if checkout is None:

        messages.info(
            request,
            "Your order is empty."
        )

        return redirect("cart")

    order_type = request.session.get(
        "checkout_order_type"
    )

    if order_type not in {
        Order.OrderType.PICKUP,
        Order.OrderType.DELIVERY,
    }:

        return redirect(
            "order_type"
        )

    address = None

    if order_type == Order.OrderType.DELIVERY:

        address_id = request.session.get(
            "checkout_address_id"
        )

        if not address_id:

            messages.info(
                request,
                "Please select a delivery address."
            )

            request.session.pop(
                "checkout_address_modal",
                None
            )

            request.session.modified = True

            return redirect(
                "order_type"
            )

        address = (
            request.user.addresses
            .filter(id=address_id)
            .first()
        )

        if address is None:

            request.session.pop(
                "checkout_address_id",
                None
            )

            request.session.pop(
                "checkout_address_modal",
                None
            )

            request.session.modified = True

            messages.info(
                request,
                "Please select a delivery address."
            )

            return redirect(
                "order_type"
            )

    if request.method == "POST":

        coupon_code = request.POST.get(
            "coupon_code",
            ""
        ).strip()

        if coupon_code:

            result = apply_coupon(
                coupon_code,
                checkout["subtotal"],
            )

            if result["success"]:

                request.session[
                    "checkout_coupon_code"
                ] = result["coupon"].code

                messages.success(
                    request,
                    result["message"]
                )

            else:

                request.session.pop(
                    "checkout_coupon_code",
                    None
                )

                messages.error(
                    request,
                    result["message"]
                )

        else:

            request.session.pop(
                "checkout_coupon_code",
                None
            )

            messages.info(
                request,
                "Coupon removed."
            )

        request.session.modified = True

        return redirect(
            "final_checkout"
        )

    coupon_code = request.session.get(
        "checkout_coupon_code"
    )

    discount = Decimal("0.00")
    applied_coupon = None

    if coupon_code:

        result = apply_coupon(
            coupon_code,
            checkout["subtotal"],
        )

        if result["success"]:

            applied_coupon = result["coupon"]
            discount = result["discount"]

        else:

            request.session.pop(
                "checkout_coupon_code",
                None
            )

            request.session.modified = True

    gst = checkout["gst"]

    total = (
        checkout["subtotal"]
        + gst
        - discount
    )

    checkout["discount"] = discount
    checkout["total"] = total

    wallet = get_customer_wallet(request.user)

    return render(
        request,
        "users_panel/final_checkout.html",
        {
            **checkout,
            "order_type": order_type,
            "address": address,
            "payment_method": "cod",
            "wallet": wallet,
            "applied_coupon": applied_coupon,
        }
    )

@login_required(login_url="login")
@require_POST
@transaction.atomic
def place_order(request):

    checkout = _get_checkout_cart(request)

    if checkout is None:
        messages.error(
            request,
            "Your order is empty."
        )
        return redirect("cart")

    # ----------------------------------------------------------
    # PAYMENT METHOD
    # ----------------------------------------------------------

    payment_method = request.POST.get(
        "payment_method",
        "cod",
    ).strip().lower()

    if payment_method not in {
        "cod",
        "wallet",
    }:
        messages.error(
            request,
            "Please choose a valid payment method."
        )
        return redirect("final_checkout")

    # ----------------------------------------------------------
    # DELIVERY ADDRESS
    # ----------------------------------------------------------

    order_type = request.session.get(
        "checkout_order_type"
    )

    if order_type not in {
        Order.OrderType.PICKUP,
        Order.OrderType.DELIVERY,
    }:
        return redirect("order_type")

    address = None

    if order_type == Order.OrderType.DELIVERY:

        address_id = request.session.get(
            "checkout_address_id"
        )

        if not address_id:
            messages.error(
                request,
                "Please select a delivery address."
            )
            return redirect("order_type")

        address = (
            request.user.addresses
            .filter(id=address_id)
            .first()
        )

        if address is None:
            messages.error(
                request,
                "The selected address is no longer available."
            )
            return redirect("order_type")

    # ----------------------------------------------------------
    # COUPON
    # ----------------------------------------------------------

    coupon = None
    discount = Decimal("0.00")

    coupon_code = request.session.get(
        "checkout_coupon_code",
        ""
    )

    if coupon_code:

        result = apply_coupon(
            coupon_code,
            checkout["subtotal"]
        )

        if not result["success"]:

            request.session.pop(
                "checkout_coupon_code",
                None
            )

            request.session.modified = True

            messages.error(
                request,
                result["message"]
            )

            return redirect("final_checkout")

        coupon = result["coupon"]
        discount = result["discount"]

    subtotal = checkout["subtotal"]
    tax_amount = checkout["gst"]

    total = (
        subtotal
        + tax_amount
        - discount
    ).quantize(
        Decimal("0.01")
    )

    # ----------------------------------------------------------
    # CREATE ORDER
    #
    # Everything is inside the same transaction.
    # If wallet payment fails later, this order is rolled back.
    # ----------------------------------------------------------

    order = Order.objects.create(

        user=request.user,

        order_no=_generate_order_number(),

        tracking_no=None,

        order_type=order_type,

        address_name=(
            address.name if address else None
        ),

        address_contact_number=(
            address.contact_number if address else None
        ),

        address_flat_house=(
            address.flat_house if address else None
        ),

        address_area_street=(
            address.area_street if address else None
        ),

        address_city=(
            address.city if address else None
        ),

        address_state=(
            address.state if address else None
        ),

        address_pincode=(
            address.pincode if address else None
        ),

        table=None,

        status=Order.Status.CONFIRMED,

        subtotal=subtotal,

        tax_percentage=checkout["tax_percentage"],

        tax_amount=tax_amount,

        coupon_code=(
            coupon.code if coupon else ""
        ),

        coupon_discount_type=(
            coupon.discount_type
            if coupon
            else ""
        ),

        coupon_discount_value=(
            coupon.discount_value
            if coupon
            else None
        ),

        coupon_minimum_order_amount=(
            coupon.minimum_order_amount
            if coupon
            else None
        ),

        coupon_maximum_discount_amount=(
            coupon.maximum_discount_amount
            if coupon
            else None
        ),

        discount_amount=discount,

        total_amount=total,
    )

    # ----------------------------------------------------------
    # CREATE ORDER ITEMS
    # ----------------------------------------------------------

    for item in checkout["cart_items"]:

        product = item["product"]

        OrderItem.objects.create(
            order=order,
            product=product,
            quantity=item["quantity"],
            unit_price=product.price,
            instructions=item["instructions"],
            subtotal=item["item_total"],
        )

    # ----------------------------------------------------------
    # RECORD COUPON USAGE
    # ----------------------------------------------------------

    if coupon:

        coupon.used_count += 1

        coupon.save(
            update_fields=[
                "used_count",
                "updated_at",
            ]
        )

    # ----------------------------------------------------------
    # WALLET PAYMENT
    # ----------------------------------------------------------

    if payment_method == "wallet":

        try:

            debit_wallet(
                user=request.user,
                amount=total,
                transaction_type=(
                    WalletTransaction.TransactionType.PAYMENT
                ),
                order=order,
                description=(
                    f"Wallet payment for order "
                    f"{order.order_no}."
                ),
            )

        except ValidationError as exc:

            messages.error(
                request,
                str(exc)
            )

            return redirect(
                "final_checkout"
            )

        # ------------------------------------------------------
        # PAID BILL
        # ------------------------------------------------------

        bill = Bill.objects.create(
            subtotal=subtotal - discount,
            tax_amount=tax_amount,
            total_amount=total,
            payment_method=Bill.PaymentMethod.ONLINE,
            transaction_method=(
                Bill.TransactionMethod.WALLET
            ),
            status=Bill.Status.PAID,
            issued_at=timezone.now(),
        )

        # ------------------------------------------------------
        # BILL ORDER
        # ------------------------------------------------------

        BillOrder.objects.create(
            order=order,
            bill=bill,
            total=total,
            payment_method=(
                BillOrder.PaymentMethod.ONLINE
            ),
        )

        # ------------------------------------------------------
        # PAYMENT RECORD
        # ------------------------------------------------------

        Payment.objects.create(
            bill=bill,
            transaction_method=(
                Payment.TransactionMethod.WALLET
            ),
            amount=total,
            payment_reference=None,
            status=Payment.Status.SUCCESSFUL,
            gateway=None,
            gateway_order_id=None,
            gateway_payment_id=None,
            gateway_event_id=None,
            paid_at=timezone.now(),
        )

        request.session[
            "last_order_payment_method"
        ] = "Online - Wallet"

    # ----------------------------------------------------------
    # CASH ON DELIVERY
    # ----------------------------------------------------------

    else:

        BillOrder.objects.create(
            order=order,
            total=order.total_amount,
            payment_method=(
                BillOrder.PaymentMethod.COD
            ),
        )

        request.session[
            "last_order_payment_method"
        ] = "Cash on Delivery"

    # ----------------------------------------------------------
    # CLEAR CHECKOUT SESSION
    # ----------------------------------------------------------

    request.session.pop(
        "cart",
        None
    )

    request.session.pop(
        "checkout_order_type",
        None
    )

    request.session.pop(
        "checkout_address_id",
        None
    )

    request.session.pop(
        "checkout_address_modal",
        None
    )

    request.session.pop(
        "checkout_coupon_code",
        None
    )

    request.session.pop(
        "razorpay_pending_checkout",
        None
    )

    request.session.modified = True

    return redirect(
        "order_detail",
        order_id=order.id
    )

def _is_paid_online_order(order):
    """
    Return True only when the order has an Online BillOrder,
    its associated Bill is paid, and a successful original
    payment exists.
    """
    bill_order = getattr(order, "bill_order", None)

    if not bill_order:
        return False

    if bill_order.payment_method != BillOrder.PaymentMethod.ONLINE:
        return False

    bill = bill_order.bill

    if not bill or bill.status != Bill.Status.PAID:
        return False

    return Payment.objects.filter(
        bill=bill,
        status=Payment.Status.SUCCESSFUL,
        refund_request__isnull=True,
        refund_of__isnull=True,
    ).exists()


def _has_active_refund_request(order):
    """
    An order-level request conflicts with every item-level
    request, and vice versa.

    Rejected requests do not block a new request.
    """
    return RefundRequest.objects.filter(
        order=order,
        status__in=[
            RefundRequest.Status.PENDING,
            RefundRequest.Status.ACCEPTED,
            RefundRequest.Status.COMPLETED,
        ],
    ).exists()


def _has_active_order_refund_request(order):
    """
    Check whether an order-level refund request is already
    pending or has been accepted/completed.
    """
    return RefundRequest.objects.filter(
        order=order,
        refund_type=RefundRequest.RefundType.ORDER,
        status__in=[
            RefundRequest.Status.PENDING,
            RefundRequest.Status.ACCEPTED,
            RefundRequest.Status.COMPLETED,
        ],
    ).exists()

@login_required(login_url="login")
def order_detail(request, order_id):
    order = get_object_or_404(
        Order.objects.prefetch_related(
            "items__product__images"
        ),
        id=order_id,
        user=request.user,
    )

    bill_order = getattr(order, "bill_order", None)

    can_cancel = order.status in {
        Order.Status.CONFIRMED,
        Order.Status.PREPARING,
    }

    is_paid_online = _is_paid_online_order(order)

    active_items = [
        item
        for item in order.items.all()
        if not item.is_cancelled
    ]

    refund_requests = list(
        RefundRequest.objects.filter(
            order=order
        ).select_related(
            "order_item",
            "reviewed_by",
        ).order_by("-created_at")
    )

    active_refund_statuses = {
        RefundRequest.Status.PENDING,
        RefundRequest.Status.ACCEPTED,
        RefundRequest.Status.COMPLETED,
    }

    # Find the latest non-rejected order-level request.
    active_order_refund = next(
        (
            refund
            for refund in refund_requests
            if refund.refund_type == RefundRequest.RefundType.ORDER
            and refund.status in active_refund_statuses
        ),
        None,
    )

    # Find the latest non-rejected refund request for each item.
    active_item_refunds = {}

    for refund in refund_requests:
        if (
            refund.refund_type == RefundRequest.RefundType.ITEM
            and refund.order_item_id
            and refund.status in active_refund_statuses
        ):
            active_item_refunds.setdefault(
                refund.order_item_id,
                refund,
            )

    # Attach the relevant request to each item so the template
    # can show its status without complicated dictionary lookups.
    for item in order.items.all():
        item.refund_request = next(
            (
                refund
                for refund in refund_requests
                if refund.order_item_id == item.id
            ),
            None,
        )

        item.active_refund_request = active_item_refunds.get(
            item.id
        )

        item.can_request_refund = (
            is_paid_online
            and can_cancel
            and not item.is_cancelled
            and active_order_refund is None
            and item.id not in active_item_refunds
        )

    can_request_order_refund = (
        is_paid_online
        and can_cancel
        and active_order_refund is None
        and not active_item_refunds
    )

    return render(
        request,
        "users_panel/order_detail.html",
        {
            "order": order,
            "bill_order": bill_order,
            "payment_method": (
                bill_order.get_payment_method_display()
                if bill_order
                else "—"
            ),
            "can_cancel": can_cancel,
            "active_items": active_items,
            "can_save_as_usual": bool(active_items),

            # Refund workflow context
            "is_paid_online": is_paid_online,
            "refund_requests": refund_requests,
            "active_order_refund": active_order_refund,
            "can_request_order_refund": (
                can_request_order_refund
            ),
        },
    )

@login_required(login_url="login")
@require_POST
@transaction.atomic
def cancel_order_item(request, item_id):

    item = get_object_or_404(
        OrderItem.objects.select_related("order"),
        id=item_id,
        order__user=request.user,
    )

    order = (
        Order.objects
        .select_for_update()
        .get(id=item.order_id)
    )

    if order.status not in {
        Order.Status.CONFIRMED,
        Order.Status.PREPARING,
    }:
        messages.error(
            request,
            "Items can no longer be removed from this order."
        )

        return redirect(
            "order_detail",
            order_id=order.id
        )

    if item.is_cancelled:
        messages.info(
            request,
            "This item has already been cancelled."
        )

        return redirect(
            "order_detail",
            order_id=order.id
        )

    reason = request.POST.get(
        "reason",
        ""
    ).strip()

    if _is_paid_online_order(order):
        messages.error(
            request,
            "Paid online items must be cancelled through a refund request. "
            "Your item has not been cancelled.",
        )
        return redirect("order_detail", order_id=order.id)

    item.is_cancelled = True
    item.cancellation_reason = reason
    item.cancelled_at = timezone.now()

    item.save(
        update_fields=[
            "is_cancelled",
            "cancellation_reason",
            "cancelled_at",
        ]
    )

    _recalculate_order_totals(order)

    remaining_items = order.items.filter(
        is_cancelled=False
    ).exists()

    if not remaining_items:

        order.status = Order.Status.CANCELLED
        order.cancelled_at = timezone.now()
        order.cancellation_reason = (
            "All items in this order were cancelled."
        )

        order.save(
            update_fields=[
                "status",
                "cancelled_at",
                "cancellation_reason",
                "updated_at",
            ]
        )

        messages.success(
            request,
            f"Order {order.order_no} has been cancelled because all items were removed."
        )

    else:

        messages.success(
            request,
            f"{item.product.name} was removed from your order."
        )

    return redirect(
        "order_detail",
        order_id=order.id
    )

@login_required(login_url="login")
@require_POST
@transaction.atomic
def admin_remove_order_item(request, order_id, item_id):
    forbidden = _admin_staff_check(request)
    if forbidden:
        return forbidden

    order = get_object_or_404(
        Order.objects.select_for_update(),
        id=order_id,
    )

    item = get_object_or_404(
        OrderItem.objects
        .select_for_update()
        .select_related("product"),
        id=item_id,
        order_id=order.id,
    )

    if item.is_cancelled:
        return JsonResponse(
            {
                "success": False,
                "message": "This item has already been removed.",
            },
            status=400,
        )

    item.is_cancelled = True
    item.cancellation_reason = (
        request.POST.get("reason", "").strip()
        or "Removed by admin."
    )
    item.cancelled_at = timezone.now()

    item.save(
        update_fields=[
            "is_cancelled",
            "cancellation_reason",
            "cancelled_at",
        ]
    )

    subtotal, tax_amount, discount, total_amount = _recalculate_order_totals(order)

    remaining_items = order.items.filter(
        is_cancelled=False
    ).exists()

    order_cancelled = False

    if not remaining_items:
        order.status = Order.Status.CANCELLED
        order.cancelled_at = timezone.now()
        order.cancellation_reason = (
            "All items in this order were removed by admin."
        )

        order.save(
            update_fields=[
                "status",
                "cancelled_at",
                "cancellation_reason",
                "updated_at",
            ]
        )

        order_cancelled = True

    return JsonResponse(
        {
            "success": True,
            "message": (
                f"{item.product.name} was removed from the order."
            ),
            "item_id": item.id,
            "item_name": item.product.name,
            "subtotal": f"{subtotal:.2f}",
            "tax_amount": f"{tax_amount:.2f}",
            "total_amount": f"{total_amount:.2f}",
            "discount_amount": f"{discount:.2f}",
            "order_cancelled": order_cancelled,
            "status": order.status,
            "status_display": order.get_status_display(),
            "updated_at": timezone.localtime(
                order.updated_at
            ).strftime("%d %b %Y, %H:%M"),
        }
    )

def _recalculate_order_totals(order):
    active_items = order.items.filter(
        is_cancelled=False
    )

    subtotal = sum(
        (
            item.subtotal
            for item in active_items
        ),
        Decimal("0.00")
    )

    tax_rate = (
        order.tax_percentage / Decimal("100")
    )

    tax_amount = (
        subtotal * tax_rate
    ).quantize(
        Decimal("0.01")
    )

    discount = Decimal("0.00")

    if order.coupon_code:
        minimum_order_amount = (
            order.coupon_minimum_order_amount
            or Decimal("0.00")
        )

        if subtotal >= minimum_order_amount:
            discount_type = order.coupon_discount_type
            discount_value = (
                order.coupon_discount_value
                or Decimal("0.00")
            )

            if discount_type == "percentage":
                discount = (
                    subtotal
                    * discount_value
                    / Decimal("100")
                )

            elif discount_type == "fixed":
                discount = discount_value

            maximum_discount = (
                order.coupon_maximum_discount_amount
            )

            if (
                maximum_discount is not None
                and discount > maximum_discount
            ):
                discount = maximum_discount

            discount = min(
                discount,
                subtotal,
            )

            discount = discount.quantize(
                Decimal("0.01")
            )

    total_amount = (
        subtotal
        + tax_amount
        - discount
    )

    order.subtotal = subtotal
    order.tax_amount = tax_amount
    order.discount_amount = discount
    order.total_amount = total_amount

    order.save(
        update_fields=[
            "subtotal",
            "tax_amount",
            "discount_amount",
            "total_amount",
            "updated_at",
        ]
    )

    return (
        subtotal,
        tax_amount,
        discount,
        total_amount,
    )

@login_required(login_url="login")
@require_POST
@transaction.atomic
def cancel_order(request, order_id):

    order = get_object_or_404(
        Order.objects.select_for_update(),
        id=order_id,
        user=request.user,
    )

    if order.status not in {
        Order.Status.CONFIRMED,
        Order.Status.PREPARING,
    }:
        messages.error(
            request,
            "This order can no longer be cancelled."
        )

        return redirect(
            "order_detail",
            order_id=order.id
        )

    reason = request.POST.get(
        "reason",
        ""
    ).strip()

    if _is_paid_online_order(order):
        messages.error(
            request,
            "A paid online order requires an approved refund request "
            "before it can be cancelled.",
        )
        return redirect("order_detail", order_id=order.id)

    order.status = Order.Status.CANCELLED
    order.cancellation_reason = reason
    order.cancelled_at = timezone.now()

    order.save(
        update_fields=[
            "status",
            "cancellation_reason",
            "cancelled_at",
            "updated_at",
        ]
    )

    order.items.filter(
        is_cancelled=False
    ).update(
        is_cancelled=True,
        cancellation_reason=reason,
        cancelled_at=timezone.now(),
    )

    messages.success(
        request,
        f"Order {order.order_no} has been cancelled."
    )

    return redirect(
        "order_detail",
        order_id=order.id
    )

@login_required(login_url="login")
@require_POST
@transaction.atomic
def request_item_refund(request, item_id):
    item = get_object_or_404(
        OrderItem.objects.select_related("order", "product"),
        id=item_id,
        order__user=request.user,
    )

    order = Order.objects.select_for_update().get(
        id=item.order_id,
    )

    # Refresh the item state after obtaining the order lock.
    item = OrderItem.objects.select_for_update().get(
        id=item.id,
        order=order,
    )

    if order.status not in {
        Order.Status.CONFIRMED,
        Order.Status.PREPARING,
    }:
        messages.error(
            request,
            "Items can no longer be removed from this order.",
        )
        return redirect("order_detail", order_id=order.id)

    if not _is_paid_online_order(order):
        messages.error(
            request,
            "This item is not eligible for an online-payment refund request.",
        )
        return redirect("order_detail", order_id=order.id)

    if item.is_cancelled:
        messages.info(
            request,
            "This item has already been cancelled.",
        )
        return redirect("order_detail", order_id=order.id)

    reason = request.POST.get("reason", "").strip()

    if not reason:
        messages.error(
            request,
            "Please provide a reason for requesting an item refund.",
        )
        return redirect("order_detail", order_id=order.id)

    bill_order = order.bill_order
    bill = bill_order.bill

    # A full-order refund conflicts with any item refund.
    if _has_active_order_refund_request(order):
        messages.error(
            request,
            "An active full-order refund request already exists.",
        )
        return redirect("order_detail", order_id=order.id)

    # Do not allow a duplicate active request for this item.
    duplicate_item_request = RefundRequest.objects.filter(
        order=order,
        order_item=item,
        refund_type=RefundRequest.RefundType.ITEM,
        status__in=[
            RefundRequest.Status.PENDING,
            RefundRequest.Status.ACCEPTED,
            RefundRequest.Status.COMPLETED,
        ],
    ).exists()

    if duplicate_item_request:
        messages.error(
            request,
            "A refund request already exists for this item.",
        )
        return redirect("order_detail", order_id=order.id)

    # The amount is based on the order's final total, allocated
    # proportionally to this item's subtotal.
    if order.subtotal <= Decimal("0.00"):
        messages.error(
            request,
            "A refund request cannot be submitted for this item.",
        )
        return redirect("order_detail", order_id=order.id)

    amount = (
        order.total_amount * item.subtotal / order.subtotal
    ).quantize(Decimal("0.01"))

    if amount <= Decimal("0.00"):
        messages.error(
            request,
            "A refund request cannot be submitted for a zero-value item.",
        )
        return redirect("order_detail", order_id=order.id)

    RefundRequest.objects.create(
        user=request.user,
        order=order,
        order_item=item,
        bill=bill,
        refund_type=RefundRequest.RefundType.ITEM,
        amount=amount,
        reason=reason,
    )

    # Important: the item remains active until admin approval.

    messages.success(
        request,
        f"Your refund request for {item.product.name} has been submitted. "
        "The item will remain in your order until the request is reviewed.",
    )

    return redirect("order_detail", order_id=order.id)

@login_required(login_url="login")
@require_POST
@transaction.atomic
def request_order_refund(request, order_id):
    order = get_object_or_404(
        Order.objects.select_for_update(),
        id=order_id,
        user=request.user,
    )

    # Refund requests are allowed only before the order reaches READY.
    if order.status not in {
        Order.Status.CONFIRMED,
        Order.Status.PREPARING,
    }:
        messages.error(
            request,
            "A refund request can no longer be submitted for this order.",
        )
        return redirect("order_detail", order_id=order.id)

    if not _is_paid_online_order(order):
        messages.error(
            request,
            "This order is not eligible for an online-payment refund request.",
        )
        return redirect("order_detail", order_id=order.id)

    reason = request.POST.get("reason", "").strip()

    if not reason:
        messages.error(
            request,
            "Please provide a reason for requesting a refund.",
        )
        return redirect("order_detail", order_id=order.id)

    bill_order = order.bill_order
    bill = bill_order.bill

    # Prevent duplicate requests and conflicts with item requests.
    if _has_active_refund_request(order):
        messages.error(
            request,
            "A refund request already exists for this order or one of its items.",
        )
        return redirect("order_detail", order_id=order.id)

    amount = order.total_amount

    if amount is None or amount <= Decimal("0.00"):
        messages.error(
            request,
            "A refund request cannot be submitted for a zero-value order.",
        )
        return redirect("order_detail", order_id=order.id)

    RefundRequest.objects.create(
        user=request.user,
        order=order,
        order_item=None,
        bill=bill,
        refund_type=RefundRequest.RefundType.ORDER,
        amount=amount,
        reason=reason,
    )

    # Important: the order is NOT cancelled here.
    # Cancellation and wallet crediting happen only after admin approval.

    messages.success(
        request,
        "Your refund request has been submitted. "
        "Your order will remain active until the request is reviewed.",
    )

    return redirect("order_detail", order_id=order.id)

@login_required(login_url="login")
def placed_orders(request):

    orders = (
        Order.objects
        .filter(user=request.user)
        .prefetch_related(
            "items"
        )
        .order_by("-created_at")
    )

    search = request.GET.get(
        "q",
        ""
    ).strip()

    status_filter = request.GET.get(
        "status",
        ""
    ).strip()

    date_filter = request.GET.get(
        "date",
        ""
    ).strip()

    if search:
        orders = orders.filter(
            order_no__icontains=search
        )

    valid_statuses = {
        choice[0]
        for choice in Order.Status.choices
    }

    if status_filter in valid_statuses:
        orders = orders.filter(
            status=status_filter
        )

    now = timezone.localtime(
        timezone.now()
    )

    today = now.date()

    if date_filter == "today":

        orders = orders.filter(
            created_at__date=today
        )

    elif date_filter == "this_week":

        start_of_week = today - timedelta(
            days=today.weekday()
        )

        orders = orders.filter(
            created_at__date__gte=start_of_week
        )

    elif date_filter == "this_month":

        orders = orders.filter(
            created_at__year=today.year,
            created_at__month=today.month,
        )

    elif date_filter == "last_month":

        first_of_this_month = today.replace(
            day=1
        )

        last_month_end = (
            first_of_this_month
            - timedelta(days=1)
        )

        last_month_start = (
            last_month_end.replace(day=1)
        )

        orders = orders.filter(
            created_at__date__gte=last_month_start,
            created_at__date__lte=last_month_end,
        )

    current_statuses = {
        Order.Status.CONFIRMED,
        Order.Status.PREPARING,
        Order.Status.READY,
    }

    current_orders = [
        order
        for order in orders
        if order.status in current_statuses
    ]

    past_orders = [
        order
        for order in orders
        if order.status in {
            Order.Status.DELIVERED,
            Order.Status.CANCELLED,
        }
    ]

    return render(
        request,
        "users_panel/placed_orders.html",
        {
            "orders": orders,
            "current_orders": current_orders,
            "past_orders": past_orders,
            "search": search,
            "status_filter": status_filter,
            "date_filter": date_filter,
        }
    )

def _admin_staff_check(request):
    if not request.user.is_staff:
        return HttpResponse(
            "You do not have permission to access this page.",
            status=403,
        )
    return None

@login_required(login_url="login")
def admin_dashboard(request):
    forbidden = _admin_staff_check(request)

    if forbidden:
        return forbidden

    tax = _get_current_tax()

    period = request.GET.get("period", "today").strip()

    start_date_param = request.GET.get("start_date", "").strip()
    end_date_param = request.GET.get("end_date", "").strip()

    now = timezone.localtime(timezone.now())
    today = now.date()

    if period == "custom":
        try:
            start_date = datetime.strptime(
                start_date_param,
                "%Y-%m-%d",
            ).date()

            end_date = datetime.strptime(
                end_date_param,
                "%Y-%m-%d",
            ).date()

            if start_date > end_date:
                period = "today"
                start_date = today
                end_date = today

        except ValueError:
            period = "today"
            start_date = today
            end_date = today

    elif period == "this_week":
        start_date = today - timedelta(days=today.weekday())
        end_date = today

    elif period == "this_month":
        start_date = today.replace(day=1)
        end_date = today

    elif period == "this_year":
        start_date = today.replace(
            month=1,
            day=1,
        )
        end_date = today

    else:
        period = "today"
        start_date = today
        end_date = today

    period_orders = (
        Order.objects
        .filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
        )
        .select_related(
            "user",
            "table",
        )
    )

    total_orders = period_orders.count()

    pending_orders = (
        period_orders
        .exclude(
            status__in=[
                Order.Status.CANCELLED,
                Order.Status.DELIVERED,
            ]
        )
        .count()
    )

    total_sales = (
        period_orders
        .exclude(
            status=Order.Status.CANCELLED
        )
        .aggregate(
            total=Sum(
                "total_amount"
            )
        )["total"]
        or Decimal("0.00")
    )

    recent_orders = (
        period_orders
        .annotate(
            item_count=Count(
                "items",
                filter=Q(
                    items__is_cancelled=False
                ),
            )
        )
        .order_by(
            "-created_at"
        )[:5]
    )

    best_selling_products = (
        OrderItem.objects
        .filter(
            is_cancelled=False,
            order__created_at__date__gte=start_date,
            order__created_at__date__lte=end_date,
        )
        .exclude(
            order__status=Order.Status.CANCELLED
        )
        .values(
            "product_id",
            "product__name",
        )
        .annotate(
            order_count=Count(
                "order_id",
                distinct=True,
            ),
            quantity=Sum(
                "quantity"
            ),
            revenue=Sum(
                "subtotal"
            ),
        )
        .order_by(
            "-quantity",
            "-revenue",
        )[:10]
    )

    best_selling_categories = (
        OrderItem.objects
        .filter(
            is_cancelled=False,
            order__created_at__date__gte=start_date,
            order__created_at__date__lte=end_date,
        )
        .exclude(
            order__status=Order.Status.CANCELLED
        )
        .values(
            "product__category_id",
            "product__category__name",
        )
        .annotate(
            order_count=Count(
                "order_id",
                distinct=True,
            ),
            quantity=Sum(
                "quantity"
            ),
            revenue=Sum(
                "subtotal"
            ),
        )
        .order_by(
            "-quantity",
            "-revenue",
        )[:10]
    )

    pickup_count = period_orders.filter(
        order_type=Order.OrderType.PICKUP
    ).count()

    delivery_count = period_orders.filter(
        order_type=Order.OrderType.DELIVERY
    ).count()

    table_count = period_orders.filter(
        order_type=Order.OrderType.TABLE
    ).count()

    orders_by_type_counts = [
        {
            "type": "pickup",
            "label": "Pickup",
            "count": pickup_count,
        },
        {
            "type": "delivery",
            "label": "Delivery",
            "count": delivery_count,
        },
        {
            "type": "table",
            "label": "Dine-in",
            "count": table_count,
        },
    ]

    orders_by_type = []

    for item in orders_by_type_counts:
        if total_orders:
            percentage = (
                Decimal(item["count"])
                * Decimal("100")
                / Decimal(total_orders)
            )
        else:
            percentage = Decimal("0.00")

        orders_by_type.append(
            {
                "type": item["type"],
                "label": item["label"],
                "count": item["count"],
                "percentage": percentage,
            }
        )

    unpaid_bills = None

    return render(
        request,
        "admin_panel/dashboard.html",
        {
            "period": period,
            "start_date": start_date,
            "end_date": end_date,
            "start_date_value": start_date.strftime("%Y-%m-%d"),
            "end_date_value": end_date.strftime("%Y-%m-%d"),
            "tax_percentage": tax.percentage,
            "total_sales": total_sales,
            "total_orders": total_orders,
            "pending_orders": pending_orders,
            "unpaid_bills": unpaid_bills,
            "best_selling_products": best_selling_products,
            "best_selling_categories": best_selling_categories,
            "recent_orders": recent_orders,
            "orders_by_type": orders_by_type,
        },
    )

@login_required(login_url="login")
@require_POST
def admin_update_tax(request):
    forbidden = _admin_staff_check(request)

    if forbidden:
        return forbidden

    percentage = request.POST.get("percentage", "").strip()

    try:
        percentage = Decimal(percentage)
    except Exception:
        messages.error(
            request,
            "Please enter a valid GST percentage.",
        )
        return redirect("admin_dashboard")

    if percentage < 0 or percentage > 100:
        messages.error(
            request,
            "GST percentage must be between 0 and 100.",
        )
        return redirect("admin_dashboard")

    tax = _get_current_tax()
    tax.percentage = percentage
    tax.save(update_fields=["percentage"])

    messages.success(
        request,
        f"GST updated to {percentage:.2f}%.",
    )

    return redirect("admin_dashboard")


@login_required(login_url="login")
def admin_order_list(request):
    forbidden = _admin_staff_check(request)

    if forbidden:
        return forbidden

    search = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()
    order_type_filter = request.GET.get("type", "").strip()
    date_filter = request.GET.get("date", "").strip()
    sort = request.GET.get("sort", "newest").strip()

    orders = (
        Order.objects
        .select_related("user", "table")
        .all()
    )

    if search:
        search_filter = (
            Q(order_no__icontains=search)
            | Q(tracking_no__icontains=search)
            | Q(user__name__icontains=search)
            | Q(user__email__icontains=search)
            | Q(items__product__name__icontains=search)
        )

        if search.isdigit():
            search_filter |= Q(user_id=int(search))

        orders = orders.filter(search_filter)
        orders = orders.filter(
            Q(items__product__name__icontains=search)
        ).distinct()

    valid_statuses = {
        choice[0]
        for choice in Order.Status.choices
    }

    if status_filter in valid_statuses:
        orders = orders.filter(status=status_filter)

    valid_order_types = {
        choice[0]
        for choice in Order.OrderType.choices
    }

    if order_type_filter in valid_order_types:
        orders = orders.filter(order_type=order_type_filter)

    now = timezone.localtime(timezone.now())
    today = now.date()

    if date_filter == "today":

        orders = orders.filter(
            created_at__date=today
        )

    elif date_filter == "this_week":

        start_of_week = today - timedelta(
            days=today.weekday()
        )

        orders = orders.filter(
            created_at__date__gte=start_of_week
        )

    elif date_filter == "this_month":

        orders = orders.filter(
            created_at__year=today.year,
            created_at__month=today.month,
        )

    elif date_filter == "last_month":

        first_of_this_month = today.replace(day=1)

        last_month_end = (
            first_of_this_month - timedelta(days=1)
        )

        last_month_start = last_month_end.replace(day=1)

        orders = orders.filter(
            created_at__date__gte=last_month_start,
            created_at__date__lte=last_month_end,
        )

    sort_options = {
        "newest": "-created_at",
        "oldest": "created_at",
        "amount_high": "-total_amount",
        "amount_low": "total_amount",
        "order_asc": "order_no",
        "order_desc": "-order_no",
    }

    order_by = sort_options.get(
        sort,
        "-created_at",
    )

    orders = orders.order_by(
        order_by,
        "-id",
    )

    paginator = Paginator(
        orders,
        ADMIN_ORDER_PAGE_SIZE,
    )

    page_obj = paginator.get_page(
        request.GET.get("page")
    )

    return render(
        request,
        "admin_panel/orders.html",
        {
            "page_obj": page_obj,
            "search": search,
            "status_filter": status_filter,
            "order_type_filter": order_type_filter,
            "date_filter": date_filter,
            "sort": sort,
            "status_choices": Order.Status.choices,
            "order_type_choices": Order.OrderType.choices,
            "total_orders": paginator.count,
        },
    )


@login_required(login_url="login")
def admin_order_detail(request, order_id):
    forbidden = _admin_staff_check(request)

    if forbidden:
        return forbidden

    order = get_object_or_404(
        Order.objects
        .select_related(
            "user",
            "table",
            "bill_order__bill",
        )
        .prefetch_related(
            "items__product__images"
        ),
        id=order_id,
    )

    can_remove_items = True

    bill_order = getattr(
        order,
        "bill_order",
        None,
    )

    payment_method = "—"

    if bill_order:

        payment_method = (
            bill_order.get_payment_method_display()
        )

        bill = bill_order.bill

        if (
            bill
            and bill.payment_method
            == Bill.PaymentMethod.ONLINE
            and bill.transaction_method
        ):
            payment_method = (
                f"{bill.get_payment_method_display()} - "
                f"{bill.get_transaction_method_display()}"
            )

    return render(
        request,
        "admin_panel/order_detail.html",
        {
            "order": order,
            "status_choices": Order.Status.choices,
            "can_remove_items": can_remove_items,
            "bill_order": bill_order,
            "payment_method": payment_method,
        },
    )


@login_required(login_url="login")
@require_POST
@transaction.atomic
def admin_update_order_status(request, order_id):
    forbidden = _admin_staff_check(request)

    if forbidden:
        return forbidden

    order = get_object_or_404(
        Order.objects.select_for_update(),
        id=order_id,
    )

    new_status = request.POST.get(
        "status",
        "",
    ).strip()

    valid_statuses = {
        choice[0]
        for choice in Order.Status.choices
    }

    if new_status not in valid_statuses:
        return JsonResponse(
            {
                "success": False,
                "message": "Invalid order status.",
            },
            status=400,
        )

    if order.status == new_status:
        return JsonResponse(
            {
                "success": True,
                "message": "Order status is already up to date.",
                "order_id": order.id,
                "order_no": order.order_no,
                "status": order.status,
                "status_display": order.get_status_display(),
            }
        )

    if order.status == Order.Status.CANCELLED:
        return JsonResponse(
            {
                "success": False,
                "message": (
                    "A cancelled order cannot be updated."
                ),
                "order_id": order.id,
                "order_no": order.order_no,
                "status": order.status,
                "status_display": order.get_status_display(),
            },
            status=400,
        )

    status_order = {
        Order.Status.CONFIRMED: 0,
        Order.Status.PREPARING: 1,
        Order.Status.READY: 2,
        Order.Status.DELIVERED: 3,
    }

    current_status = order.status

    requires_confirmation = (
        new_status == Order.Status.CANCELLED
        or (
            current_status in status_order
            and new_status in status_order
            and status_order[new_status] < status_order[current_status]
        )
    )

    confirmed = request.POST.get("confirmed") == "true"

    if requires_confirmation and not confirmed:
        return JsonResponse(
            {
                "success": False,
                "requires_confirmation": True,
                "message": (
                    f"Changing order status from "
                    f"{order.get_status_display()} to "
                    f"{order.get_status_display() if False else dict(Order.Status.choices).get(new_status, new_status)} "
                    "requires confirmation."
                ),
            },
            status=409,
        )

    order.status = new_status

    update_fields = [
        "status",
        "updated_at",
    ]

    if new_status == Order.Status.CANCELLED:

        if not order.cancelled_at:
            order.cancelled_at = timezone.now()
            update_fields.append("cancelled_at")

    else:

        if order.cancelled_at:
            order.cancelled_at = None
            update_fields.append("cancelled_at")

        if order.cancellation_reason:
            order.cancellation_reason = ""
            update_fields.append("cancellation_reason")

    order.save(
        update_fields=update_fields
    )

    if new_status == Order.Status.DELIVERED:
        reward_referral_for_order(order)

    return JsonResponse(
        {
            "success": True,
            "message": "Order status updated successfully.",
            "order_id": order.id,
            "order_no": order.order_no,
            "status": order.status,
            "status_display": order.get_status_display(),
            "updated_at": timezone.localtime(
                order.updated_at
            ).strftime(
                "%d %b %Y, %H:%M"
            ),
        }
    )