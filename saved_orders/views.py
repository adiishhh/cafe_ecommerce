from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from product.models import Product
from .models import SavedOrder, SavedOrderItem

# Create your views here.

def _clear_saved_order_session(request):
    request.session.pop(
        "save_order_mode",
        None
    )

    request.session.pop(
        "saved_order_edit_id",
        None
    )

    request.session.modified = True


@login_required
def my_usuals(request):

    saved_orders = (
        SavedOrder.objects
        .filter(user=request.user)
        .prefetch_related("items__product")
        .order_by("-updated_at")
    )

    return render(
        request,
        "users_panel/my_usuals.html",
        {
            "saved_orders": saved_orders,
        },
    )


@login_required
def create_usual(request):

    request.session["save_order_mode"] = True

    request.session.pop(
        "saved_order_edit_id",
        None
    )

    request.session["cart"] = {}

    request.session.modified = True

    return redirect("home")


@login_required
@require_POST
def save_usual(request):

    cart = request.session.get(
        "cart",
        {}
    )

    if not cart:
        messages.error(
            request,
            "Your usual cannot be saved because it is empty."
        )

        return redirect("cart")

    name = request.POST.get(
        "name",
        ""
    ).strip()

    edit_id = request.session.get(
        "saved_order_edit_id"
    )

    if edit_id:

        saved_order = get_object_or_404(
            SavedOrder,
            id=edit_id,
            user=request.user,
        )

        with transaction.atomic():

            saved_order.name = name

            saved_order.save(
                update_fields=[
                    "name",
                    "updated_at",
                ]
            )

            saved_order.items.all().delete()

            _create_saved_items(
                saved_order,
                cart,
            )

    else:

        with transaction.atomic():

            saved_order = SavedOrder.objects.create(
                user=request.user,
                name=name,
            )

            _create_saved_items(
                saved_order,
                cart,
            )

    request.session.pop(
        "cart",
        None
    )

    _clear_saved_order_session(
        request
    )

    messages.success(
        request,
        "Your usual has been saved."
    )

    return redirect(
        "my_usuals"
    )


def _create_saved_items(saved_order, cart):

    product_ids = [
        int(product_id)
        for product_id in cart.keys()
    ]

    products = Product.objects.in_bulk(
        product_ids
    )

    items = []

    for product_id, cart_item in cart.items():

        product = products.get(
            int(product_id)
        )

        if not product:
            continue

        if isinstance(cart_item, int):

            quantity = cart_item
            instructions = ""

        else:

            quantity = int(
                cart_item.get(
                    "quantity",
                    0
                )
            )

            instructions = cart_item.get(
                "instructions",
                ""
            ).strip()

        if quantity < 1:
            continue

        items.append(
            SavedOrderItem(
                saved_order=saved_order,
                product=product,
                quantity=quantity,
                instructions=instructions,
            )
        )

    SavedOrderItem.objects.bulk_create(
        items
    )


@login_required
@require_POST
def delete_usual(request, saved_order_id):

    saved_order = get_object_or_404(
        SavedOrder,
        id=saved_order_id,
        user=request.user,
    )

    saved_order.delete()

    messages.success(
        request,
        "Your usual has been deleted."
    )

    return redirect(
        "my_usuals"
    )


@login_required
@require_POST
def order_again(request, saved_order_id):

    saved_order = get_object_or_404(
        SavedOrder.objects.prefetch_related(
            "items"
        ),
        id=saved_order_id,
        user=request.user,
    )

    cart = {}

    for item in saved_order.items.all():

        cart[str(item.product_id)] = {
            "quantity": item.quantity,
            "instructions": item.instructions,
        }

    request.session["cart"] = cart
    request.session.pop(
        "save_order_mode",
        None
    )

    request.session.pop(
        "saved_order_edit_id",
        None
    )

    request.session.modified = True

    return redirect(
        "cart"
    )


@login_required
@require_POST
def edit_usual(request, saved_order_id):

    saved_order = get_object_or_404(
        SavedOrder.objects.prefetch_related(
            "items"
        ),
        id=saved_order_id,
        user=request.user,
    )

    cart = {}

    for item in saved_order.items.all():

        cart[str(item.product_id)] = {
            "quantity": item.quantity,
            "instructions": item.instructions,
        }

    request.session["cart"] = cart

    request.session["save_order_mode"] = True

    request.session["saved_order_edit_id"] = (
        saved_order.id
    )

    request.session.modified = True

    return redirect(
        "cart"
    )