from django.shortcuts import render, redirect, get_object_or_404
from decimal import Decimal
from django.contrib.auth.decorators import login_required
from product.models import Product
import random
from django.contrib import messages
from django.db import transaction
from django.views.decorators.http import require_POST
from product.models import Product
from users.models import Address
from .models import Order, OrderItem
from django.http import HttpResponse
from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,)
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta

# Create your views here.

GST_RATE = Decimal("0.05")
MAX_CART_QUANTITY = 10


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

    gst = (
        subtotal * GST_RATE
    ).quantize(
        Decimal("0.01")
    )

    total = subtotal + gst

    return {
        "cart_items": cart_items,
        "cart_count": cart_count,
        "subtotal": subtotal,
        "gst": gst,
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

            request.session[
                "checkout_address_modal"
            ] = False

            request.session.modified = True

            return redirect("final_checkout")

        request.session[
            "checkout_address_modal"
        ] = True

        request.session.modified = True

    selected_type = request.session.get(
        "checkout_order_type"
    )

    selected_address = None

    if (
        selected_type
        == Order.OrderType.DELIVERY
    ):

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

    addresses = request.user.addresses.all().order_by(
        "-is_default",
        "-id"
    )

    address_modal = request.session.get(
        "checkout_address_modal",
        False
    )

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

            request.session[
                "checkout_address_modal"
            ] = True

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

            request.session[
                "checkout_address_modal"
            ] = True

            request.session.modified = True

            messages.info(
                request,
                "Please select a delivery address."
            )

            return redirect(
                "order_type"
            )

    return render(
        request,
        "users_panel/final_checkout.html",
        {
            **checkout,
            "order_type": order_type,
            "address": address,
            "payment_method": "cod",
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

            messages.error(
                request,
                "Please select a delivery address."
            )

            return redirect(
                "order_type"
            )

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

            return redirect(
                "order_type"
            )

    order = Order.objects.create(
        user=request.user,
        order_no=_generate_order_number(),
        tracking_no=None,
        order_type=order_type,
        address=address,
        table=None,
        status=Order.Status.CONFIRMED,
        subtotal=checkout["subtotal"],
        tax_amount=checkout["gst"],
        total_amount=checkout["total"],
    )

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

    request.session[
        "last_order_payment_method"
    ] = "Cash on Delivery"

    request.session.modified = True

    return redirect(
        "order_detail",
        order_id=order.id
    )


@login_required(login_url="login")
def order_detail(request, order_id):

    order = get_object_or_404(
        Order.objects
        .prefetch_related(
            "items__product__images"
        ),
        id=order_id,
        user=request.user,
    )

    payment_method = request.session.pop(
        "last_order_payment_method",
        "Cash on Delivery"
    )

    request.session.modified = True

    can_cancel = order.status in {
        Order.Status.CONFIRMED,
        Order.Status.PREPARING,
    }

    active_items = [
        item
        for item in order.items.all()
        if not item.is_cancelled
    ]

    return render(
        request,
        "users_panel/order_detail.html",
        {
            "order": order,
            "payment_method": payment_method,
            "can_cancel": can_cancel,
            "active_items": active_items,
        }
    )

@login_required(login_url="login")
def download_invoice(request, order_id):
    order = get_object_or_404(
        Order.objects.prefetch_related(
            "items__product"
        ),
        id=order_id,
        user=request.user,
    )

    response = HttpResponse(
        content_type="application/pdf"
    )

    response[
        "Content-Disposition"
    ] = (
        f'attachment; '
        f'filename="SmartCafe_{order.order_no}.pdf"'
    )

    document = SimpleDocTemplate(
        response,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )

    styles = getSampleStyleSheet()

    brand_style = ParagraphStyle(
        "Brand",
        parent=styles["Title"],
        fontSize=22,
        leading=26,
        alignment=TA_CENTER,
        spaceAfter=6,
    )

    invoice_title_style = ParagraphStyle(
        "InvoiceTitle",
        parent=styles["Heading2"],
        fontSize=15,
        leading=18,
        alignment=TA_CENTER,
        spaceAfter=16,
    )

    normal_style = ParagraphStyle(
        "NormalCustom",
        parent=styles["Normal"],
        fontSize=9,
        leading=13,
    )

    small_style = ParagraphStyle(
        "Small",
        parent=styles["Normal"],
        fontSize=8,
        leading=11,
    )

    right_style = ParagraphStyle(
        "Right",
        parent=normal_style,
        alignment=TA_RIGHT,
    )

    elements = []

    elements.append(
        Paragraph(
            "SMARTCAFE",
            brand_style,
        )
    )

    elements.append(
        Paragraph(
            "INVOICE",
            invoice_title_style,
        )
    )

    elements.append(
        Spacer(
            1,
            5 * mm,
        )
    )

    order_type = order.get_order_type_display()

    payment_method = (
        "Cash on Delivery"
    )

    order_information = [
        [
            Paragraph(
                "<b>Order Number</b>",
                normal_style,
            ),
            Paragraph(
                order.order_no,
                normal_style,
            ),
        ],
        [
            Paragraph(
                "<b>Order Date</b>",
                normal_style,
            ),
            Paragraph(
                order.created_at.strftime(
                    "%d %b %Y, %I:%M %p"
                ),
                normal_style,
            ),
        ],
        [
            Paragraph(
                "<b>Order Type</b>",
                normal_style,
            ),
            Paragraph(
                order_type,
                normal_style,
            ),
        ],
        [
            Paragraph(
                "<b>Payment Method</b>",
                normal_style,
            ),
            Paragraph(
                payment_method,
                normal_style,
            ),
        ],
    ]

    order_table = Table(
        order_information,
        colWidths=[
            45 * mm,
            115 * mm,
        ],
    )

    order_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, -1),
                    colors.whitesmoke,
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.lightgrey,
                ),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.25,
                    colors.lightgrey,
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE",
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
            ]
        )
    )

    elements.append(order_table)

    elements.append(
        Spacer(
            1,
            8 * mm,
        )
    )

    elements.append(
        Paragraph(
            "<b>Customer Information</b>",
            normal_style,
        )
    )

    elements.append(
        Spacer(
            1,
            2 * mm,
        )
    )

    customer = order.user

    customer_information = [
        [
            Paragraph(
                "<b>Name</b>",
                normal_style,
            ),
            Paragraph(
                customer.name,
                normal_style,
            ),
        ],
        [
            Paragraph(
                "<b>Email</b>",
                normal_style,
            ),
            Paragraph(
                customer.email,
                normal_style,
            ),
        ],
        [
            Paragraph(
                "<b>Phone</b>",
                normal_style,
            ),
            Paragraph(
                customer.phone,
                normal_style,
            ),
        ],
    ]

    customer_table = Table(
        customer_information,
        colWidths=[
            45 * mm,
            115 * mm,
        ],
    )

    customer_table.setStyle(
        TableStyle(
            [
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.lightgrey,
                ),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.25,
                    colors.lightgrey,
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
            ]
        )
    )

    elements.append(customer_table)

    if (
        order.order_type
        == Order.OrderType.DELIVERY
        and order.address
    ):
        elements.append(
            Spacer(
                1,
                8 * mm,
            )
        )

        elements.append(
            Paragraph(
                "<b>Delivery Address</b>",
                normal_style,
            )
        )

        elements.append(
            Spacer(
                1,
                2 * mm,
            )
        )

        address = order.address

        address_text = (
            f"<b>{address.name}</b><br/>"
            f"{address.flat_house}, "
            f"{address.area_street}<br/>"
            f"{address.city}, "
            f"{address.state} - "
            f"{address.pincode}<br/>"
            f"{address.contact_number}"
        )

        elements.append(
            Paragraph(
                address_text,
                normal_style,
            )
        )

    elements.append(
        Spacer(
            1,
            10 * mm,
        )
    )

    elements.append(
        Paragraph(
            "<b>Order Items</b>",
            normal_style,
        )
    )

    elements.append(
        Spacer(
            1,
            3 * mm,
        )
    )

    item_rows = [
        [
            Paragraph(
                "<b>Item</b>",
                small_style,
            ),
            Paragraph(
                "<b>Qty</b>",
                small_style,
            ),
            Paragraph(
                "<b>Unit Price</b>",
                right_style,
            ),
            Paragraph(
                "<b>Total</b>",
                right_style,
            ),
        ]
    ]

    for item in order.items.all():

        item_rows.append(
            [
                Paragraph(
                    item.product.name,
                    small_style,
                ),
                Paragraph(
                    str(item.quantity),
                    small_style,
                ),
                Paragraph(
                    f"₹{item.unit_price}",
                    right_style,
                ),
                Paragraph(
                    f"₹{item.subtotal}",
                    right_style,
                ),
            ]
        )

        if item.instructions:
            item_rows.append(
                [
                    Paragraph(
                        f"<i>Note: "
                        f"{item.instructions}</i>",
                        small_style,
                    ),
                    "",
                    "",
                    "",
                ]
            )

    items_table = Table(
        item_rows,
        colWidths=[
            80 * mm,
            18 * mm,
            32 * mm,
            30 * mm,
        ],
        repeatRows=1,
    )

    items_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor("#f1e6d8"),
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.lightgrey,
                ),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.25,
                    colors.lightgrey,
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP",
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
            ]
        )
    )

    elements.append(items_table)

    elements.append(
        Spacer(
            1,
            8 * mm,
        )
    )

    summary_rows = [
        [
            Paragraph(
                "Subtotal",
                normal_style,
            ),
            Paragraph(
                f"₹{order.subtotal}",
                right_style,
            ),
        ],
        [
            Paragraph(
                "GST (5%)",
                normal_style,
            ),
            Paragraph(
                f"₹{order.tax_amount}",
                right_style,
            ),
        ],
        [
            Paragraph(
                "Shipping",
                normal_style,
            ),
            Paragraph(
                "₹0.00",
                right_style,
            ),
        ],
        [
            Paragraph(
                "Discount",
                normal_style,
            ),
            Paragraph(
                "₹0.00",
                right_style,
            ),
        ],
        [
            Paragraph(
                "<b>Total</b>",
                normal_style,
            ),
            Paragraph(
                f"<b>₹{order.total_amount}</b>",
                right_style,
            ),
        ],
    ]

    summary_table = Table(
        summary_rows,
        colWidths=[
            130 * mm,
            30 * mm,
        ],
    )

    summary_table.setStyle(
        TableStyle(
            [
                (
                    "LINEABOVE",
                    (0, 4),
                    (-1, 4),
                    0.8,
                    colors.grey,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
                (
                    "ALIGN",
                    (1, 0),
                    (1, -1),
                    "RIGHT",
                ),
            ]
        )
    )

    elements.append(summary_table)

    elements.append(
        Spacer(
            1,
            15 * mm,
        )
    )

    elements.append(
        Paragraph(
            "Thank you for ordering from SmartCafe!",
            ParagraphStyle(
                "Footer",
                parent=small_style,
                alignment=TA_CENTER,
                textColor=colors.grey,
            ),
        )
    )

    document.build(elements)

    return response

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

def _recalculate_order_totals(order):
    active_items = order.items.filter(
        is_cancelled=False
    )

    subtotal = sum(
        (item.subtotal for item in active_items),
        Decimal("0.00")
    )

    tax_amount = (
        subtotal * GST_RATE
    ).quantize(
        Decimal("0.01")
    )

    total_amount = subtotal + tax_amount

    order.subtotal = subtotal
    order.tax_amount = tax_amount
    order.total_amount = total_amount

    order.save(
        update_fields=[
            "subtotal",
            "tax_amount",
            "total_amount",
            "updated_at",
        ]
    )

    return subtotal, tax_amount, total_amount

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