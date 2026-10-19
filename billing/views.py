from django.shortcuts import redirect, render, get_object_or_404
from .models import Bill, BillOrder, Payment, RefundRequest, BillingSectionReadState
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.utils import timezone
from datetime import date, datetime, timedelta
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
import uuid
from django.conf import settings
import razorpay
from orders.models import Order, OrderItem
from orders.views import _get_checkout_cart
from coupons.views import apply_coupon
from coupons.models import Coupon
import logging  
from django.urls import reverse
from orders.views import _generate_order_number
from product.models import Product
from wallet.models import WalletTransaction
from wallet.views import credit_wallet
from django.db.models import Sum, Count, Q
from django.http import HttpResponse, HttpResponseBadRequest
import csv
from collections import defaultdict
from io import BytesIO
from django.core.paginator import Paginator

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

@login_required(login_url="login")
def admin_bill_list(request):
    forbidden = _admin_staff_check(request)
    if forbidden:
        return forbidden

    now = timezone.now()
    today = timezone.localtime(now).date()

    valid_views = {
        "unpaid_orders",
        "unpaid_bills",
        "paid_bills",
        "refunds",
    }

    active_view = request.GET.get("view", "unpaid_orders")

    if active_view not in valid_views:
        active_view = "unpaid_orders"

    # --------------------------------------------------
    # DATE FILTER PERSISTENCE
    # --------------------------------------------------

    session_key_start = "billing_start_date"
    session_key_end = "billing_end_date"

    clear_dates = request.GET.get("clear_dates") == "1"

    start_date_param = request.GET.get("start_date", "").strip()
    end_date_param = request.GET.get("end_date", "").strip()

    def parse_date(value):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None

    if clear_dates:
        # Explicit reset: both dates return to today.
        start_date = today
        end_date = today

    elif start_date_param or end_date_param:
        # A submitted date filter becomes the new saved range.
        start_date = parse_date(start_date_param) or today
        end_date = parse_date(end_date_param) or today

    elif (
        request.session.get(session_key_start)
        and request.session.get(session_key_end)
    ):
        # Navigating between sections preserves the range.
        start_date = (
            parse_date(request.session[session_key_start]) or today
        )
        end_date = (
            parse_date(request.session[session_key_end]) or today
        )

    else:
        # First visit: default to today.
        start_date = today
        end_date = today

    if start_date > end_date:
        start_date = today
        end_date = today

    request.session[session_key_start] = start_date.strftime("%Y-%m-%d")
    request.session[session_key_end] = end_date.strftime("%Y-%m-%d")

    # --------------------------------------------------
    # UNREAD SECTION TRACKING
    # --------------------------------------------------

    section_choices = [
        BillingSectionReadState.Section.UNPAID_ORDERS,
        BillingSectionReadState.Section.UNPAID_BILLS,
        BillingSectionReadState.Section.PAID_BILLS,
        BillingSectionReadState.Section.REFUNDS,
    ]

    # Establish a baseline on the admin's first visit.
    # This prevents all historical records from appearing
    # as newly unread.
    for section in section_choices:
        BillingSectionReadState.objects.get_or_create(
            user=request.user,
            section=section,
            defaults={"last_viewed_at": now},
        )

    # Mark only the currently opened section as viewed.
    BillingSectionReadState.objects.filter(
        user=request.user,
        section=active_view,
    ).update(last_viewed_at=now)

    read_states = {
        state.section: state.last_viewed_at
        for state in BillingSectionReadState.objects.filter(
            user=request.user,
        )
    }

    # --------------------------------------------------
    # DATE-FILTERED SECTION CONTENT
    # --------------------------------------------------

    unpaid_orders = (
        BillOrder.objects
        .filter(
            bill__isnull=True,
            payment_method=BillOrder.PaymentMethod.COD,
            order__status=Order.Status.DELIVERED,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
        )
        .select_related(
            "order",
            "order__user",
        )
        .prefetch_related(
            "order__items__product",
        )
        .order_by("-created_at", "-id")
    )

    unpaid_bills = (
        Bill.objects
        .filter(
            status=Bill.Status.UNPAID,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
        )
        .prefetch_related(
            "bill_orders__order",
            "bill_orders__order__user",
        )
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
        RefundRequest.objects
        .filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
        )
        .select_related(
            "user",
            "order",
            "order_item",
            "order_item__product",
            "bill",
            "reviewed_by",
            "refund_payment",
        )
        .order_by("-created_at", "-id")
    )

    # --------------------------------------------------
    # UNREAD COUNTS
    #
    # These are independent of the selected date filter.
    # --------------------------------------------------

    unread_unpaid_orders = BillOrder.objects.filter(
        bill__isnull=True,
        payment_method=BillOrder.PaymentMethod.COD,
        order__status=Order.Status.DELIVERED,
        created_at__gt=read_states["unpaid_orders"],
    ).count()

    unread_unpaid_bills = Bill.objects.filter(
        status=Bill.Status.UNPAID,
        created_at__gt=read_states["unpaid_bills"],
    ).count()

    unread_paid_bills = Bill.objects.filter(
        status=Bill.Status.PAID,
        updated_at__gt=read_states["paid_bills"],
    ).count()

    unread_refunds = RefundRequest.objects.filter(
        created_at__gt=read_states["refunds"],
    ).count()

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

            "unread_unpaid_orders": unread_unpaid_orders,
            "unread_unpaid_bills": unread_unpaid_bills,
            "unread_paid_bills": unread_paid_bills,
            "unread_refunds": unread_refunds,
        },
    )

@login_required(login_url="login")
@require_POST
@transaction.atomic
def admin_review_refund(request, refund_id):
    forbidden = _admin_staff_check(request)

    if forbidden:
        return JsonResponse(
            {
                "success": False,
                "message": "Permission denied.",
            },
            status=403,
        )

    action = request.POST.get("action", "").strip().lower()
    admin_note = request.POST.get("admin_note", "").strip()

    if action not in {"accept", "reject"}:
        return JsonResponse(
            {
                "success": False,
                "message": "Invalid refund action.",
            },
            status=400,
        )

    refund = get_object_or_404(
        RefundRequest.objects.select_for_update(),
        id=refund_id,
    )

    if refund.status != RefundRequest.Status.PENDING:
        return JsonResponse(
            {
                "success": False,
                "message": "This refund request has already been reviewed.",
            },
            status=409,
        )

    if action == "reject" and not admin_note:
        return JsonResponse(
            {
                "success": False,
                "message": "An explanation is required when rejecting a refund.",
            },
            status=400,
        )

    if action == "reject":
        refund.status = RefundRequest.Status.REJECTED
        refund.admin_note = admin_note
        refund.reviewed_by = request.user
        refund.reviewed_at = timezone.now()

        refund.save(
            update_fields=[
                "status",
                "admin_note",
                "reviewed_by",
                "reviewed_at",
                "updated_at",
            ]
        )

        return JsonResponse(
            {
                "success": True,
                "message": "Refund request rejected.",
                "status": refund.status,
            }
        )

    # Lock the associated order before changing its status.
    order = get_object_or_404(
        Order.objects.select_for_update(),
        id=refund.order_id,
    )

    # A full-order refund must not be processed if the order
    # has already been cancelled or progressed beyond eligibility.
    if order.status not in {
        Order.Status.CONFIRMED,
        Order.Status.PREPARING,
    }:
        return JsonResponse(
            {
                "success": False,
                "message": (
                    "This order is no longer eligible for refund approval."
                ),
            },
            status=409,
        )

    # A full-order request conflicts with any other active
    # or completed refund request for the same order.
    active_statuses = [
        RefundRequest.Status.PENDING,
        RefundRequest.Status.ACCEPTED,
        RefundRequest.Status.COMPLETED,
    ]

    if refund.refund_type == RefundRequest.RefundType.ORDER:
        other_requests = RefundRequest.objects.filter(
            order=order,
            status__in=active_statuses,
        ).exclude(pk=refund.pk)

        if other_requests.exists():
            return JsonResponse(
                {
                    "success": False,
                    "message": (
                        "Another active or completed refund request "
                        "exists for this order."
                    ),
                },
                status=409,
            )

        amount = order.total_amount

    else:
        # Lock the requested item and verify that it is still active.
        item = get_object_or_404(
            OrderItem.objects.select_for_update(),
            id=refund.order_item_id,
            order=order,
        )

        if item.is_cancelled:
            return JsonResponse(
                {
                    "success": False,
                    "message": "This item has already been cancelled.",
                },
                status=409,
            )

        if RefundRequest.objects.filter(
            order=order,
            refund_type=RefundRequest.RefundType.ORDER,
            status__in=active_statuses,
        ).exclude(pk=refund.pk).exists():
            return JsonResponse(
                {
                    "success": False,
                    "message": (
                        "A full-order refund request already exists."
                    ),
                },
                status=409,
            )

        other_item_requests = RefundRequest.objects.filter(
            order=order,
            order_item=item,
            refund_type=RefundRequest.RefundType.ITEM,
            status__in=active_statuses,
        ).exclude(pk=refund.pk)

        if other_item_requests.exists():
            return JsonResponse(
                {
                    "success": False,
                    "message": (
                        "Another active or completed refund "
                        "already exists for this item."
                    ),
                },
                status=409,
            )

        amount = refund.amount

    if amount <= 0:
        return JsonResponse(
            {
                "success": False,
                "message": "The refund amount must be greater than zero.",
            },
            status=400,
        )

    # Locate the original successful payment.
    original_payment = (
        Payment.objects
        .select_for_update()
        .filter(
            bill_id=refund.bill_id,
            status=Payment.Status.SUCCESSFUL,
            refund_request__isnull=True,
            refund_of__isnull=True,
        )
        .order_by("-created_at", "-id")
        .first()
    )

    if original_payment is None:
        return JsonResponse(
            {
                "success": False,
                "message": "No successful original payment was found.",
            },
            status=409,
        )

    # Create the wallet refund payment record.
    refund_payment = Payment.objects.create(
        bill=refund.bill,
        transaction_method=Payment.TransactionMethod.WALLET,
        amount=amount,
        status=Payment.Status.SUCCESSFUL,
        refund_request=refund,
        refund_of=original_payment,
        paid_at=timezone.now(),
    )

    # Credit the customer's wallet in the same transaction.
    # Any failure rolls back the payment and status changes.
    credit_wallet(
        user=refund.user,
        amount=amount,
        transaction_type=WalletTransaction.TransactionType.REFUND,
        order=order,
        payment=refund_payment,
        refund_request=refund,
        description=(
            f"Refund for {refund.request_no}, "
            f"order {order.order_no}."
        ),
    )

    # Only now, after successful wallet credit, change the order/item.
    if refund.refund_type == RefundRequest.RefundType.ORDER:
        order.status = Order.Status.CANCELLED

        update_fields = ["status", "updated_at"]

        if hasattr(order, "cancelled_at"):
            order.cancelled_at = timezone.now()
            update_fields.append("cancelled_at")

        order.save(update_fields=update_fields)

        order.items.filter(is_cancelled=False).update(
            is_cancelled=True,
        )

    else:
        item.is_cancelled = True

        item_update_fields = ["is_cancelled"]

        if hasattr(item, "cancelled_at"):
            item.cancelled_at = timezone.now()
            item_update_fields.append("cancelled_at")

        item.save(update_fields=item_update_fields)

        # If all items have now been cancelled, mark the order cancelled.
        if not order.items.filter(is_cancelled=False).exists():
            order.status = Order.Status.CANCELLED

            order_update_fields = ["status", "updated_at"]

            if hasattr(order, "cancelled_at"):
                order.cancelled_at = timezone.now()
                order_update_fields.append("cancelled_at")

            order.save(update_fields=order_update_fields)

    refund.status = RefundRequest.Status.COMPLETED
    refund.admin_note = admin_note
    refund.reviewed_by = request.user
    refund.reviewed_at = timezone.now()
    refund.completed_at = timezone.now()

    refund.save(
        update_fields=[
            "status",
            "admin_note",
            "reviewed_by",
            "reviewed_at",
            "completed_at",
            "updated_at",
        ]
    )

    return JsonResponse(
        {
            "success": True,
            "message": "Refund approved and credited to the customer's wallet.",
            "status": refund.status,
            "refund_amount": str(amount),
            "payment_id": refund_payment.id,
        }
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
                        "Please select Cash, UPI or Card."
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

    selected_ids = list(
        dict.fromkeys(selected_ids)
    )

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

    for bill_order in bill_orders:

        bill_order.bill = bill

        bill_order.save(
            update_fields=[
                "bill",
            ],
        )

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
                "message": "Permission denied.",
            },
            status=403,
        )

    bill = get_object_or_404(
        Bill.objects.prefetch_related(
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

    # Retrieve actual successful payment records.
    # Exclude refund transactions from the original
    # payment details for this bill.
    payments = (
        bill.payments
        .filter(
            status=Payment.Status.SUCCESSFUL,
            refund_request__isnull=True,
            refund_of__isnull=True,
        )
        .order_by("-created_at", "-id")
    )

    payment_data = [
        {
            "id": payment.id,
            "amount": str(payment.amount),
            "transaction_method": payment.transaction_method,
            "transaction_method_display": (
                payment.get_transaction_method_display()
            ),
            "status": payment.status,
            "status_display": payment.get_status_display(),
            "payment_reference": payment.payment_reference or "",
            "gateway": payment.gateway or "",
            "gateway_order_id": payment.gateway_order_id or "",
            "gateway_payment_id": payment.gateway_payment_id or "",
            "paid_at": (
                timezone.localtime(payment.paid_at).strftime(
                    "%d %b %Y, %I:%M %p"
                )
                if payment.paid_at
                else ""
            ),
            "created_at": (
                timezone.localtime(payment.created_at).strftime(
                    "%d %b %Y, %I:%M %p"
                )
                if payment.created_at
                else ""
            ),
        }
        for payment in payments
    ]

    return JsonResponse({
        "success": True,

        "bill": {
            "id": bill.id,
            "bill_no": bill.bill_no,
            "status": bill.status,
            "status_display": bill.get_status_display(),
            "payment_method": bill.payment_method,
            "subtotal": str(bill.subtotal),
            "tax_amount": str(bill.tax_amount),
            "total_amount": str(bill.total_amount),
            "orders": orders,
        },

        # Transaction details come from Payment records,
        # not from the Bill model.
        "payments": payment_data,
    })

@login_required(login_url="login")
@require_GET
def admin_refund_data(request, refund_id):
    """
    Return the details of a completed refund for the
    staff-only Payment Details modal.
    """

    forbidden = _admin_staff_check(request)

    if forbidden:
        return JsonResponse(
            {
                "success": False,
                "message": "Permission denied.",
            },
            status=403,
        )

    refund = get_object_or_404(
        RefundRequest.objects.select_related(
            "user",
            "order",
            "order_item",
            "order_item__product",
            "bill",
            "reviewed_by",
            "refund_payment",
            "refund_payment__refund_of",
        ),
        id=refund_id,
    )

    # Only completed refunds have a completed payment record
    # to display in this modal.
    if refund.status != RefundRequest.Status.COMPLETED:
        return JsonResponse(
            {
                "success": False,
                "message": (
                    "Payment details are available only "
                    "for completed refunds."
                ),
            },
            status=409,
        )

    refund_payment = refund.refund_payment

    original_payment = (
        refund_payment.refund_of
        if refund_payment
        else None
    )

    wallet_transaction = (
        WalletTransaction.objects
        .filter(refund_request=refund)
        .select_related("wallet")
        .first()
    )

    customer_name = (
        getattr(refund.user, "name", "")
        or getattr(refund.user, "username", "")
        or str(refund.user)
    )

    return JsonResponse(
        {
            "success": True,
            "refund": {
                "id": refund.id,
                "request_no": refund.request_no,
                "status": refund.status,
                "status_display": refund.get_status_display(),
                "refund_type": refund.refund_type,
                "refund_type_display": (
                    refund.get_refund_type_display()
                ),
                "amount": str(refund.amount),
                "reason": refund.reason,
                "admin_note": refund.admin_note or "",
                "created_at": (
                    refund.created_at.strftime("%d %b %Y, %I:%M %p")
                    if refund.created_at
                    else ""
                ),
                "reviewed_at": (
                    refund.reviewed_at.strftime("%d %b %Y, %I:%M %p")
                    if refund.reviewed_at
                    else ""
                ),
                "completed_at": (
                    refund.completed_at.strftime("%d %b %Y, %I:%M %p")
                    if refund.completed_at
                    else ""
                ),
                "reviewed_by": (
                    str(refund.reviewed_by)
                    if refund.reviewed_by
                    else "—"
                ),
                "customer_name": customer_name,
                "customer_email": (
                    getattr(refund.user, "email", "") or "—"
                ),
                "order_no": refund.order.order_no,
                "item_name": (
                    refund.order_item.product.name
                    if refund.order_item
                    else ""
                ),
                "bill_no": (
                    refund.bill.bill_no
                    if refund.bill
                    else "—"
                ),
                "refund_payment": (
                    {
                        "id": refund_payment.id,
                        "amount": str(refund_payment.amount),
                        "transaction_method": refund_payment.transaction_method,
                        "transaction_method_display": (
                            refund_payment.get_transaction_method_display()
                        ),
                        "status": refund_payment.status,
                        "status_display": refund_payment.get_status_display(),
                        "payment_reference": refund_payment.payment_reference or "",
                        "gateway": refund_payment.gateway or "",
                        "gateway_order_id": refund_payment.gateway_order_id or "",
                        "gateway_payment_id": refund_payment.gateway_payment_id or "",
                        "paid_at": (
                            timezone.localtime(refund_payment.paid_at).strftime(
                                "%d %b %Y, %I:%M %p"
                            )
                            if refund_payment.paid_at
                            else ""
                        ),
                    }
                    if refund_payment
                    else None
                ),

                "original_payment": (
                    {
                        "id": original_payment.id,
                        "amount": str(original_payment.amount),
                        "transaction_method": original_payment.transaction_method,
                        "transaction_method_display": (
                            original_payment.get_transaction_method_display()
                        ),
                        "status": original_payment.status,
                        "status_display": original_payment.get_status_display(),
                        "payment_reference": original_payment.payment_reference or "",
                        "gateway": original_payment.gateway or "",
                        "gateway_order_id": original_payment.gateway_order_id or "",
                        "gateway_payment_id": original_payment.gateway_payment_id or "",
                        "paid_at": (
                            timezone.localtime(original_payment.paid_at).strftime(
                                "%d %b %Y, %I:%M %p"
                            )
                            if original_payment.paid_at
                            else ""
                        ),
                    }
                    if original_payment
                    else None
                ),
                "wallet_credited": (
                    str(wallet_transaction.amount)
                    if wallet_transaction
                    else "0.00"
                ),
                "wallet_balance_after": (
                    str(wallet_transaction.balance_after)
                    if wallet_transaction
                    else ""
                ),
            },
        }
    )

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
        Bill.TransactionMethod.NETBANKING,
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
            # "config_id": settings.RAZORPAY_CONFIG_ID,
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

    # An already-recorded successful callback must not create another order.
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
            "netbanking": Payment.TransactionMethod.NETBANKING,
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

        return JsonResponse(
            {
                "success": False,
                "message": (
                    "Payment verification failed. "
                    "Please contact support if money was deducted."
                ),
            },
            status=500,
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

REPORT_PERIODS = {
    "today",
    "yesterday",
    "this_week",
    "last_week",
    "this_month",
    "last_month",
    "this_year",
    "last_year",
    "custom",
}


def report_money(value):
    """Convert monetary values to Decimal safely."""
    if value is None:
        return Decimal("0.00")

    return Decimal(str(value)).quantize(Decimal("0.01"))


def get_report_dates(period, start_value=None, end_value=None):
    """
    Return the inclusive start and end dates for a report.
    Uses the current local date.
    """
    today = timezone.localdate()

    if period not in REPORT_PERIODS:
        period = "today"

    if period == "custom":
        try:
            start_date = date.fromisoformat(start_value)
            end_date = date.fromisoformat(end_value)
        except (TypeError, ValueError):
            start_date = today
            end_date = today

        if start_date > end_date:
            start_date, end_date = end_date, start_date

        return start_date, end_date, period

    if period == "today":
        start_date = end_date = today

    elif period == "yesterday":
        start_date = end_date = today - timedelta(days=1)

    elif period == "this_week":
        start_date = today - timedelta(days=today.weekday())
        end_date = today

    elif period == "last_week":
        this_week_start = today - timedelta(days=today.weekday())
        start_date = this_week_start - timedelta(days=7)
        end_date = this_week_start - timedelta(days=1)

    elif period == "this_month":
        start_date = today.replace(day=1)
        end_date = today

    elif period == "last_month":
        first_day_this_month = today.replace(day=1)
        end_date = first_day_this_month - timedelta(days=1)
        start_date = end_date.replace(day=1)

    elif period == "this_year":
        start_date = today.replace(month=1, day=1)
        end_date = today

    else:  # last_year
        start_date = date(today.year - 1, 1, 1)
        end_date = date(today.year - 1, 12, 31)

    return start_date, end_date, period

@login_required(login_url="login")
@require_GET
def admin_reports(request):
    """
    Admin financial reports.

    Reports use saved order amounts and actual Payment records.
    Product offer discounts are not reconstructed because historical
    product discount amounts are not stored separately.
    """

    # ---------------------------------------------------------
    # PERMISSION CHECK
    # ---------------------------------------------------------

    if not (request.user.is_staff or request.user.is_superuser):
        return HttpResponse(
            "You do not have permission to access this page.",
            status=403,
        )

    # ---------------------------------------------------------
    # DATE FILTERS
    # ---------------------------------------------------------

    selected_period = request.GET.get("period", "today")

    start_date, end_date, selected_period = get_report_dates(
        selected_period,
        request.GET.get("start_date"),
        request.GET.get("end_date"),
    )

    start_date_value = start_date.isoformat()
    end_date_value = end_date.isoformat()

    selected_order_type = request.GET.get("order_type", "all")

    valid_order_types = {
        choice[0]
        for choice in Order._meta.get_field("order_type").choices
    }

    if (
        selected_order_type != "all"
        and selected_order_type not in valid_order_types
    ):
        selected_order_type = "all"

    search_query = request.GET.get("search", "").strip()

    # ---------------------------------------------------------
    # BASE ORDER QUERYSET
    # ---------------------------------------------------------

    orders = Order.objects.filter(
        created_at__date__range=(start_date, end_date)
    )

    if selected_order_type != "all":
        orders = orders.filter(order_type=selected_order_type)

    if search_query:
        orders = orders.filter(order_no__icontains=search_query)

    orders = orders.order_by("-created_at", "-id")

    # All matching orders are included in the detailed report.
    total_orders = orders.count()

    completed_orders = orders.filter(
        status=Order.Status.DELIVERED
    ).count()

    # Cancelled orders remain visible in the detailed table,
    # but are excluded from the primary sales calculations.
    sales_orders = orders.exclude(
        status=Order.Status.CANCELLED
    )

    # ---------------------------------------------------------
    # FINANCIAL SUMMARY
    # ---------------------------------------------------------

    sales_totals = sales_orders.aggregate(
        order_subtotal=Sum("subtotal"),
        coupon_discounts=Sum("discount_amount"),
        total_tax=Sum("tax_amount"),
        order_total=Sum("total_amount"),
    )

    order_subtotal = report_money(
        sales_totals["order_subtotal"]
    )

    coupon_discounts = report_money(
        sales_totals["coupon_discounts"]
    )

    total_tax = report_money(
        sales_totals["total_tax"]
    )

    order_total = report_money(
        sales_totals["order_total"]
    )

    subtotal_after_coupon = (
        order_subtotal - coupon_discounts
    ).quantize(Decimal("0.01"))

    total_discounts = coupon_discounts

    # The checkout calculates tax on the subtotal before applying
    # the coupon. Therefore this is a display breakdown, not a
    # recalculation of the tax basis.
    net_sales = subtotal_after_coupon

    # ---------------------------------------------------------
    # REFUNDS
    # ---------------------------------------------------------

    # Use completed_at for refunds completed during the selected
    # period, rather than the date the refund request was created.
    refund_date_filter = {
        "status": RefundRequest.Status.COMPLETED,
        "completed_at__date__range": (start_date, end_date),
    }

    completed_refunds = RefundRequest.objects.filter(
        **refund_date_filter
    )

    if selected_order_type != "all":
        completed_refunds = completed_refunds.filter(
            order__order_type=selected_order_type
        )

    total_refunds = report_money(
        completed_refunds.aggregate(
            total=Sum("amount")
        )["total"]
    )

    completed_refund_count = completed_refunds.count()

    pending_refunds = RefundRequest.objects.filter(
        status=RefundRequest.Status.PENDING,
        created_at__date__range=(start_date, end_date),
    )

    if selected_order_type != "all":
        pending_refunds = pending_refunds.filter(
            order__order_type=selected_order_type
        )

    pending_refund_count = pending_refunds.count()

    net_after_refunds = (
        order_total - total_refunds
    ).quantize(Decimal("0.01"))

    # ---------------------------------------------------------
    # DISCOUNT ANALYSIS
    # ---------------------------------------------------------

    # The saved Order.discount_amount represents the coupon
    # deduction. Historical product-offer discount amounts are
    # not separately available in the existing schema.
    discount_rate = Decimal("0.00")

    if order_subtotal > 0:
        discount_rate = (
            total_discounts / order_subtotal * Decimal("100")
        ).quantize(Decimal("0.01"))

    # ---------------------------------------------------------
    # PAYMENT COLLECTIONS
    # ---------------------------------------------------------

    # Count only actual successful original payments.
    # Refund payment records must not be counted as collections.
    payment_queryset = Payment.objects.filter(
        status=Payment.Status.SUCCESSFUL,
        paid_at__date__range=(start_date, end_date),
        refund_request__isnull=True,
        refund_of__isnull=True,
    )

    if selected_order_type != "all":
        payment_queryset = payment_queryset.filter(
            bill__bill_orders__order__order_type=selected_order_type
        )

    payment_queryset = payment_queryset.distinct()

    payment_aggregates = (
        payment_queryset
        .values("transaction_method")
        .annotate(
            transaction_count=Count("id"),
            amount=Sum("amount"),
        )
        .order_by("transaction_method")
    )

    payment_method_rows = []

    for item in payment_aggregates:
        method = item["transaction_method"]

        # Use the model's own display labels.
        payment_method_rows.append({
            "method": method,
            "label": dict(
                Payment.TransactionMethod.choices
            ).get(method, method.title()),
            "transaction_count": item["transaction_count"],
            "amount": report_money(item["amount"]),
        })

    amount_collected = report_money(
        payment_queryset.aggregate(
            total=Sum("amount")
        )["total"]
    )

    # Outstanding is an estimate based on report-period order
    # totals less original successful collections. It is not a
    # substitute for the current balance of individual bills.
    outstanding_amount = max(
        Decimal("0.00"),
        order_total - amount_collected,
    ).quantize(Decimal("0.01"))

    collection_rate = Decimal("0.00")

    if order_total > 0:
        collection_rate = (
            amount_collected / order_total * Decimal("100")
        ).quantize(Decimal("0.01"))

    # ---------------------------------------------------------
    # DETAILED REPORT ROWS
    # ---------------------------------------------------------

    report_orders = []

    # Aggregate refunds per order to avoid repeating the same
    # refund total for every row in the detailed report.
    refunds_by_order = defaultdict(lambda: Decimal("0.00"))

    order_ids = list(orders.values_list("id", flat=True))

    if order_ids:
        order_refund_totals = (
            RefundRequest.objects.filter(
                order_id__in=order_ids,
                status=RefundRequest.Status.COMPLETED,
            )
            .values("order_id")
            .annotate(total=Sum("amount"))
        )

        for refund in order_refund_totals:
            refunds_by_order[refund["order_id"]] = report_money(
                refund["total"]
            )

    for order in orders:
        report_orders.append({
            "id": order.id,
            "order_no": order.order_no,
            "order_date": order.created_at,
            "order_type": order.get_order_type_display(),
            "status": order.status,
            "status_label": order.get_status_display(),
            "gross_amount": report_money(order.subtotal),
            "discount_amount": report_money(
                order.discount_amount
            ),
            "tax_amount": report_money(order.tax_amount),
            "order_total": report_money(order.total_amount),
            "refund_amount": refunds_by_order[order.id],
        })

    # ---------------------------------------------------------
    # EXPORTS
    # ---------------------------------------------------------

    export_format = request.GET.get("export", "").strip().lower()

    if export_format:
        return export_admin_report(
            export_format=export_format,
            report_orders=report_orders,
            start_date=start_date,
            end_date=end_date,
        )

    # ---------------------------------------------------------
    # PAGINATION
    # ---------------------------------------------------------

    paginator = Paginator(report_orders, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    # ---------------------------------------------------------
    # TEMPLATE CONTEXT
    # ---------------------------------------------------------

    context = {
        "selected_period": selected_period,
        "selected_order_type": selected_order_type,
        "start_date": start_date,
        "end_date": end_date,
        "start_date_value": start_date_value,
        "end_date_value": end_date_value,
        "search_query": search_query,

        "total_orders": total_orders,
        "completed_orders": completed_orders,

        "order_subtotal": order_subtotal,
        "gross_sales": order_subtotal,

        "total_discounts": total_discounts,
        "coupon_discounts": coupon_discounts,
        "product_discounts": Decimal("0.00"),
        "other_discounts": Decimal("0.00"),

        "subtotal_after_coupon": subtotal_after_coupon,
        "net_sales": net_sales,
        "total_tax": total_tax,
        "order_total": order_total,

        "total_refunds": total_refunds,
        "completed_refund_count": completed_refund_count,
        "pending_refund_count": pending_refund_count,
        "net_after_refunds": net_after_refunds,

        "discount_rate": discount_rate,

        "amount_collected": amount_collected,
        "outstanding_amount": outstanding_amount,
        "collection_rate": collection_rate,
        "payment_method_rows": payment_method_rows,

        "report_orders": page_obj.object_list,
        "page_obj": page_obj,

        "active_page": "reports",
    }

    return render(
        request,
        "admin_panel/reports.html",
        context,
    )

def export_admin_report(
    export_format,
    report_orders,
    start_date,
    end_date,
):
    """
    Export the filtered report to CSV, Excel or PDF.
    """

    headers = [
        "Order ID",
        "Order Date",
        "Order Type",
        "Status",
        "Order Subtotal",
        "Coupon Discount",
        "Tax",
        "Order Total",
        "Refunded Amount",
    ]

    rows = []

    for row in report_orders:
        order_date = row["order_date"]

        if timezone.is_aware(order_date):
            order_date = timezone.localtime(order_date)

        rows.append([
            row["order_no"],
            order_date.strftime("%Y-%m-%d %H:%M:%S"),
            row["order_type"],
            row["status_label"],
            str(row["gross_amount"]),
            str(row["discount_amount"]),
            str(row["tax_amount"]),
            str(row["order_total"]),
            str(row["refund_amount"]),
        ])

    filename_base = (
        f"smartcafe_report_{start_date}_{end_date}"
    )

    # ---------------------------------------------------------
    # CSV
    # ---------------------------------------------------------

    if export_format == "csv":
        response = HttpResponse(
            content_type="text/csv; charset=utf-8",
        )

        response["Content-Disposition"] = (
            f'attachment; filename="{filename_base}.csv"'
        )

        response.write("\ufeff")

        writer = csv.writer(response)
        writer.writerow(headers)
        writer.writerows(rows)

        return response

    # ---------------------------------------------------------
    # EXCEL
    # ---------------------------------------------------------

    if export_format == "excel":
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill
            from openpyxl.utils import get_column_letter
        except ImportError:
            return HttpResponse(
                "Excel export requires openpyxl. "
                "Install it with: pip install openpyxl",
                status=500,
            )

        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Sales Report"

        worksheet.append(headers)

        for cell in worksheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(
                fill_type="solid",
                fgColor="8B3F16",
            )

        for row in rows:
            worksheet.append(row)

        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions

        for column_cells in worksheet.columns:
            max_length = max(
                len(str(cell.value or ""))
                for cell in column_cells
            )

            worksheet.column_dimensions[
                get_column_letter(column_cells[0].column)
            ].width = min(max_length + 3, 30)

        output = BytesIO()
        workbook.save(output)
        output.seek(0)

        response = HttpResponse(
            output.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )

        response["Content-Disposition"] = (
            f'attachment; filename="{filename_base}.xlsx"'
        )

        return response

    # ---------------------------------------------------------
    # PDF
    # ---------------------------------------------------------

    if export_format == "pdf":
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import landscape, A4
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import (
                SimpleDocTemplate,
                Paragraph,
                Spacer,
                Table,
                TableStyle,
            )
        except ImportError:
            return HttpResponse(
                "PDF export requires ReportLab. "
                "Install it with: pip install reportlab",
                status=500,
            )

        output = BytesIO()

        document = SimpleDocTemplate(
            output,
            pagesize=landscape(A4),
            rightMargin=24,
            leftMargin=24,
            topMargin=24,
            bottomMargin=24,
        )

        styles = getSampleStyleSheet()

        elements = [
            Paragraph(
                "SmartCafe - Detailed Sales Report",
                styles["Title"],
            ),
            Spacer(1, 8),
            Paragraph(
                f"Period: {start_date} to {end_date}",
                styles["Normal"],
            ),
            Spacer(1, 16),
        ]

        table_data = [headers]

        for row in rows:
            # Paragraphs allow long order IDs or statuses to wrap.
            table_data.append([
                Paragraph(str(value), styles["BodyText"])
                for value in row
            ])

        table = Table(
            table_data,
            repeatRows=1,
        )

        table.setStyle(TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor("#8B3F16"),
            ),
            (
                "TEXTCOLOR",
                (0, 0),
                (-1, 0),
                colors.white,
            ),
            (
                "FONTNAME",
                (0, 0),
                (-1, 0),
                "Helvetica-Bold",
            ),
            (
                "FONTSIZE",
                (0, 0),
                (-1, -1),
                7,
            ),
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.4,
                colors.HexColor("#E2D8CA"),
            ),
            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "TOP",
            ),
            (
                "ROWBACKGROUNDS",
                (0, 1),
                (-1, -1),
                [
                    colors.white,
                    colors.HexColor("#FFF9F3"),
                ],
            ),
            (
                "LEFTPADDING",
                (0, 0),
                (-1, -1),
                5,
            ),
            (
                "RIGHTPADDING",
                (0, 0),
                (-1, -1),
                5,
            ),
        ]))

        elements.append(table)
        document.build(elements)

        response = HttpResponse(
            output.getvalue(),
            content_type="application/pdf",
        )

        response["Content-Disposition"] = (
            f'attachment; filename="{filename_base}.pdf"'
        )

        return response

    return HttpResponseBadRequest(
        "Unsupported export format."
    )