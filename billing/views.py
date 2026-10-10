from django.shortcuts import redirect, render, get_object_or_404
from .models import Bill, BillOrder, Payment
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.views.decorators.http import require_GET

# Create you views.

def _admin_staff_check(request):

    if not request.user.is_staff:

        messages.error(
            request,
            "You do not have permission to access the admin area.",
        )

        return redirect("home")

    return None


def _get_selected_date(request):

    date_value = request.GET.get(
        "date",
        "",
    ).strip()

    if date_value:

        try:

            return timezone.datetime.strptime(
                date_value,
                "%Y-%m-%d",
            ).date()

        except ValueError:
            pass

    return timezone.localdate()


@login_required(login_url="login")
def admin_bill_list(request):

    forbidden = _admin_staff_check(request)

    if forbidden:
        return forbidden

    # ----------------------------------------------------------
    # DATE
    # ----------------------------------------------------------

    selected_date = _get_selected_date(request)

    # ----------------------------------------------------------
    # ACTIVE SECTION
    # ----------------------------------------------------------

    active_view = request.GET.get(
        "view",
        "unpaid_orders",
    )

    valid_views = {
        "unpaid_orders",
        "unpaid_bills",
        "paid_bills",
        "refunds",
    }

    if active_view not in valid_views:
        active_view = "unpaid_orders"

    # ==========================================================
    # UNPAID ORDERS
    # ==========================================================
    #
    # These are COD BillOrders which have not yet been attached
    # to a Bill.
    #
    # Products are prefetched so the template can display the
    # items without causing an N+1 query problem.
    # ==========================================================

    unpaid_orders = (
        BillOrder.objects
        .filter(
            bill__isnull=True,
            payment_method=BillOrder.PaymentMethod.COD,
            created_at__date=selected_date,
        )
        .select_related(
            "order",
            "order__user",
        )
        .prefetch_related(
            "order__items__product",
        )
        .order_by(
            "-created_at",
            "-id",
        )
    )

    # ==========================================================
    # UNPAID BILLS
    # ==========================================================

    unpaid_bills = (
        Bill.objects
        .filter(
            status=Bill.Status.UNPAID,
            created_at__date=selected_date,
        )
        .prefetch_related(
            "bill_orders__order",
            "bill_orders__order__user",
        )
        .order_by(
            "-created_at",
            "-id",
        )
    )

    # ==========================================================
    # PAID BILLS
    # ==========================================================

    paid_bills = (
        Bill.objects
        .filter(
            status=Bill.Status.PAID,
            created_at__date=selected_date,
        )
        .prefetch_related(
            "bill_orders__order",
            "bill_orders__order__user",
            "payments",
        )
        .order_by(
            "-created_at",
            "-id",
        )
    )

    # ==========================================================
    # REFUNDS
    # ==========================================================

    refunds = (
        Payment.objects
        .filter(
            status=Payment.Status.REFUNDED,
            created_at__date=selected_date,
        )
        .select_related(
            "bill",
        )
        .order_by(
            "-created_at",
            "-id",
        )
    )

    return render(
        request,
        "admin_panel/bills.html",
        {
            "active_view": active_view,
            "selected_date": selected_date,

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