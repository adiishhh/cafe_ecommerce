from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.core.paginator import Paginator
from django.db.models import (
    Q,
    Avg,
    Count,
    F,
    Value,
    Case,
    When,
    ExpressionWrapper,
    DecimalField,
)
from django.contrib import messages
from django.views.decorators.http import require_POST
from .forms import ProductForm, ProductImageFormSet
from .models import Product
from orders.models import Tax
from category.models import Category
from tables.views import get_qr_table
from decimal import Decimal, InvalidOperation
from django.utils import timezone
from .models import ReviewRating
from django.http import HttpResponseBadRequest, Http404, HttpResponse
from django.core.files.storage import default_storage
import json
import uuid
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile


def _get_current_tax():
    tax = Tax.objects.first()

    if tax is None:
        tax = Tax.objects.create(percentage=Decimal("5.00"))

    return tax


def customer_home(request):

    if request.user.is_staff:
        return redirect("admin_users")

    query = request.GET.get("q", "").strip()
    category_id = request.GET.get("category", "").strip()
    sort = request.GET.get("sort", "").strip()
    min_price = request.GET.get("min_price", "").strip()
    max_price = request.GET.get("max_price", "").strip()

    today = timezone.localdate()

    price_field = DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    products = (
        Product.objects.select_related("category")
        .prefetch_related("images")
        .annotate(
            effective_price=Case(
                When(
                    offer_percentage__gt=0,
                    offer_valid_until__gte=today,
                    then=ExpressionWrapper(
                        F("base_price")
                        * (
                            Value(Decimal("100.00"), output_field=price_field)
                            - F("offer_percentage")
                        )
                        / Value(Decimal("100.00"), output_field=price_field),
                        output_field=price_field,
                    ),
                ),
                default=F("base_price"),
                output_field=price_field,
            )
        )
    )

    if query:
        products = products.filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(category__name__icontains=query)
        )

    if category_id:
        products = products.filter(category_id=category_id)

    if min_price:
        try:
            min_price_value = Decimal(min_price)

            if min_price_value >= 0:
                products = products.filter(effective_price__gte=min_price_value)
            else:
                min_price = ""

        except (InvalidOperation, ValueError):
            min_price = ""

    if max_price:
        try:
            max_price_value = Decimal(max_price)

            if max_price_value >= 0:
                products = products.filter(effective_price__lte=max_price_value)
            else:
                max_price = ""

        except (InvalidOperation, ValueError):
            max_price = ""

    if sort == "price_low":

        products = products.order_by("effective_price")

    elif sort == "price_high":

        products = products.order_by("-effective_price")

    elif sort == "name_az":

        products = products.order_by("name")

    elif sort == "name_za":

        products = products.order_by("-name")

    else:

        products = products.order_by("-created_at")

    paginator = Paginator(products, 16)

    page_number = request.GET.get("page")

    page_obj = paginator.get_page(page_number)

    categories = Category.objects.filter(is_active=True).order_by("name")

    cart = request.session.get("cart", {})

    cart_count = 0
    cart_total = Decimal("0.00")

    if cart:

        cart_products = Product.objects.filter(
            id__in=cart.keys(), is_active=True, category__is_active=True
        )

        for product in cart_products:
            item = cart.get(str(product.id), {})

            if isinstance(item, int):
                quantity = item
            else:
                quantity = int(item.get("quantity", 0))

            cart_count += quantity

            cart_total += product.price * quantity

    context = {
        "page_obj": page_obj,
        "categories": categories,
        "query": query,
        "category_id": category_id,
        "sort": sort,
        "min_price": min_price,
        "max_price": max_price,
        "cart_count": cart_count,
        "cart_total": cart_total,
        "today": timezone.localdate(),
    }

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":

        return render(request, "users_panel/users_products.html", context)

    return render(request, "users_panel/home.html", context)


def customer_product_detail(request, product_id):
    product = get_object_or_404(
        Product.objects.select_related("category").prefetch_related("images"),
        id=product_id,
    )

    reviews = (
        ReviewRating.objects.filter(product=product)
        .select_related("user", "replied_by")
        .order_by("-created_at", "-id")
    )

    rating_summary = reviews.aggregate(
        average_rating=Avg("rating"), total_reviews=Count("id")
    )

    average_rating = rating_summary["average_rating"] or 0
    total_reviews = rating_summary["total_reviews"]

    user_review = None

    if request.user.is_authenticated and not request.user.is_staff:
        user_review = ReviewRating.objects.filter(
            product=product, user=request.user
        ).first()

    related_products_queryset = (
        Product.objects.select_related("category")
        .prefetch_related("images")
        .filter(category=product.category)
        .exclude(id=product.id)
        .order_by("-created_at", "-id")
    )

    related_products_count = related_products_queryset.count()

    related_products = list(related_products_queryset[:4])

    related_page = 0
    has_previous_related = False
    has_next_related = related_products_count > 4

    first_review = reviews.first()

    displayed_reviews = [first_review] if first_review is not None else []

    review = first_review
    review_index = 0

    has_previous_review = False
    has_next_review = total_reviews > 1

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    section = request.GET.get("section")

    if is_ajax and section == "related_products":

        try:
            related_page = int(request.GET.get("page", 0))
        except (TypeError, ValueError):
            return HttpResponseBadRequest("Invalid related-products page.")

        if related_page < 0:
            return HttpResponseBadRequest("Invalid related-products page.")

        start = related_page * 4
        end = start + 4

        related_products = list(related_products_queryset[start:end])

        if related_page > 0 and not related_products:
            return HttpResponseBadRequest("No related products found for this page.")

        has_previous_related = related_page > 0
        has_next_related = end < related_products_count

    elif is_ajax and section == "reviews":

        try:
            review_index = int(request.GET.get("index", 0))
        except (TypeError, ValueError):
            return HttpResponseBadRequest("Invalid review index.")

        if review_index < 0 or review_index >= total_reviews:
            return HttpResponseBadRequest("Invalid review index.")

        review = reviews[review_index : review_index + 1].first()

        if review is None:
            return HttpResponseBadRequest("Review not found.")

        displayed_reviews = [review]

        has_previous_review = review_index > 0
        has_next_review = review_index < total_reviews - 1

    elif is_ajax:
        return HttpResponseBadRequest("Invalid AJAX section.")

    context = {
        "product": product,
        "related_products": related_products,
        "related_products_count": related_products_count,
        "related_page": related_page,
        "has_previous_related": has_previous_related,
        "has_next_related": has_next_related,
        "average_rating": average_rating,
        "total_reviews": total_reviews,
        "reviews": displayed_reviews,
        "review": review,
        "review_index": review_index,
        "has_previous_review": has_previous_review,
        "has_next_review": has_next_review,
        "user_review": user_review,
        "rating_choices": range(1, 6),
    }

    return render(request, "users_panel/product_detail.html", context)


@login_required(login_url="login")
@require_POST
def submit_product_review(request, product_id):

    if request.user.is_staff:
        return HttpResponseForbidden("Administrators cannot submit customer reviews.")

    product = get_object_or_404(
        Product.objects.select_related("category"), id=product_id
    )

    if not product.is_active or not product.category.is_active:

        messages.error(request, "You cannot review an unavailable product.")

        return redirect("customer_product_detail", product_id=product.id)

    rating_value = request.POST.get("rating", "").strip()

    review_text = request.POST.get("review", "").strip()

    try:
        rating_value = int(rating_value)
    except (TypeError, ValueError):
        rating_value = 0

    if rating_value not in range(1, 6):

        messages.error(request, "Please select a rating between 1 and 5 stars.")

        return redirect("customer_product_detail", product_id=product.id)

    if not review_text:

        messages.error(request, "Please enter your review.")

        return redirect("customer_product_detail", product_id=product.id)

    if len(review_text) > 2000:

        messages.error(request, "Your review cannot exceed 2000 characters.")

        return redirect("customer_product_detail", product_id=product.id)

    review_obj, created = ReviewRating.objects.get_or_create(
        product=product,
        user=request.user,
        defaults={
            "rating": rating_value,
            "review": review_text,
        },
    )

    if not created:

        review_obj.rating = rating_value
        review_obj.review = review_text
        review_obj.save(
            update_fields=[
                "rating",
                "review",
                "updated_at",
            ]
        )

        messages.success(request, "Your review has been updated.")

    else:

        messages.success(request, "Thank you! Your review has been submitted.")

    return redirect("customer_product_detail", product_id=product.id)


@login_required(login_url="login")
@require_POST
def delete_product_review(request, product_id):

    if request.user.is_staff:
        return HttpResponseForbidden("Administrators cannot use this customer action.")

    review = get_object_or_404(ReviewRating, product_id=product_id, user=request.user)

    review.delete()

    messages.success(request, "Your review has been deleted.")

    return redirect("customer_product_detail", product_id=product_id)


@login_required(login_url="login")
@require_POST
def admin_review_reply(request, review_id):

    if not request.user.is_staff:
        return HttpResponseForbidden("You are not authorized to reply to reviews.")

    review_obj = get_object_or_404(
        ReviewRating.objects.select_related("product"), id=review_id
    )

    reply_text = request.POST.get("admin_reply", "").strip()

    if not reply_text:

        messages.error(request, "Please enter a reply before submitting.")

        return redirect("product_detail", product_id=review_obj.product_id)

    if len(reply_text) > 2000:

        messages.error(request, "The reply cannot exceed 2000 characters.")

        return redirect("product_detail", product_id=review_obj.product_id)

    review_obj.admin_reply = reply_text
    review_obj.replied_by = request.user
    review_obj.replied_at = timezone.now()

    review_obj.save(
        update_fields=[
            "admin_reply",
            "replied_by",
            "replied_at",
            "updated_at",
        ]
    )

    messages.success(request, "Your reply has been saved.")

    return redirect("product_detail", product_id=review_obj.product_id)


@login_required(login_url="login")
@require_POST
def admin_delete_review_reply(request, review_id):

    if not request.user.is_staff:
        return HttpResponseForbidden("You are not authorized to delete review replies.")

    review_obj = get_object_or_404(
        ReviewRating.objects.select_related("product"), id=review_id
    )

    if not review_obj.admin_reply:

        messages.info(request, "This review does not have a reply to delete.")

    else:

        review_obj.admin_reply = ""
        review_obj.replied_by = None
        review_obj.replied_at = None

        review_obj.save(
            update_fields=[
                "admin_reply",
                "replied_by",
                "replied_at",
                "updated_at",
            ]
        )

        messages.success(request, "Reply deleted successfully.")

    return redirect("product_detail", product_id=review_obj.product_id)


@login_required(login_url="login")
@require_POST
def admin_delete_product_review(request, review_id):

    if not request.user.is_staff:
        return HttpResponseForbidden(
            "You are not authorized to delete customer reviews."
        )

    review_obj = get_object_or_404(
        ReviewRating.objects.select_related("product"), id=review_id
    )

    product_id = review_obj.product_id

    review_obj.delete()

    messages.success(request, "Customer review deleted successfully.")

    return redirect("product_detail", product_id=product_id)


MAX_CART_QUANTITY = 10


def _get_cart_item(cart, product_id):
    product_key = str(product_id)
    item = cart.get(product_key)

    if item is None:
        return None

    if isinstance(item, int):
        return {
            "quantity": item,
            "instructions": "",
        }

    return {
        "quantity": int(item.get("quantity", 0)),
        "instructions": item.get("instructions", "").strip(),
    }


def _save_cart_item(cart, product_id, quantity, instructions=""):
    cart[str(product_id)] = {
        "quantity": quantity,
        "instructions": instructions.strip(),
    }


@require_POST
def add_to_cart(request, product_id):

    product = get_object_or_404(
        Product.objects.select_related("category"),
        id=product_id,
    )

    if not product.is_active or not product.category.is_active:

        messages.error(request, "This product is currently unavailable.")

        return redirect(
            "customer_product_detail",
            product_id=product.id,
        )

    try:
        quantity = int(request.POST.get("quantity", 1))
    except (TypeError, ValueError):
        quantity = 1

    if quantity < 1:
        quantity = 1

    if quantity > MAX_CART_QUANTITY:

        messages.error(
            request, f"You can add a maximum of {MAX_CART_QUANTITY} of this product."
        )

        return redirect(
            "customer_product_detail",
            product_id=product.id,
        )

    instructions = request.POST.get("instructions", "").strip()

    cart = request.session.get("cart", {})

    product_key = str(product.id)

    existing_item = _get_cart_item(cart, product.id)

    current_quantity = existing_item["quantity"] if existing_item else 0

    new_quantity = current_quantity + quantity

    if new_quantity > MAX_CART_QUANTITY:

        messages.error(
            request,
            f'Maximum quantity for "{product.name}" ' f"is {MAX_CART_QUANTITY}.",
        )

        return redirect(
            "customer_product_detail",
            product_id=product.id,
        )

    if not instructions and existing_item:
        instructions = existing_item["instructions"]

    _save_cart_item(
        cart,
        product.id,
        new_quantity,
        instructions,
    )

    request.session["cart"] = cart
    request.session.modified = True

    get_qr_table(request, update_activity=True)

    if request.session.get("save_order_mode"):

        messages.success(request, f"{product.name} added to your usual.")

    else:

        messages.success(request, f"{product.name} added to your order.")

    return redirect("home")


def cart(request):

    session_cart = request.session.get("cart", {})

    save_order_mode = request.session.get(
        "save_order_mode",
        False,
    )

    saved_order_edit_id = request.session.get("saved_order_edit_id")

    saved_order_edit_name = request.session.get(
        "saved_order_edit_name",
        "",
    )

    if not session_cart:

        return render(
            request,
            "users_panel/cart.html",
            {
                "cart_items": [],
                "cart_count": 0,
                "subtotal": Decimal("0.00"),
                "gst": Decimal("0.00"),
                "total": Decimal("0.00"),
                "has_unavailable_items": False,
                "save_order_mode": save_order_mode,
                "saved_order_edit_id": saved_order_edit_id,
                "saved_order_edit_name": saved_order_edit_name,
            },
        )

    products = (
        Product.objects.select_related("category")
        .prefetch_related("images")
        .filter(id__in=session_cart.keys())
    )

    cart_items = []

    subtotal = Decimal("0.00")
    cart_count = 0
    has_unavailable_items = False

    for product in products:

        item = _get_cart_item(session_cart, product.id)

        if not item:
            continue

        quantity = item["quantity"]

        if quantity < 1:
            continue

        quantity = min(quantity, MAX_CART_QUANTITY)

        instructions = item["instructions"]

        is_available = product.is_active and product.category.is_active

        if is_available:

            item_total = product.price * quantity

            subtotal += item_total

        else:

            item_total = Decimal("0.00")
            has_unavailable_items = True

        cart_count += quantity

        cart_items.append(
            {
                "product": product,
                "quantity": quantity,
                "instructions": instructions,
                "item_total": item_total,
                "is_available": is_available,
            }
        )

    tax = _get_current_tax()
    tax_percentage = tax.percentage

    tax_rate = tax_percentage / Decimal("100")

    gst = (subtotal * tax_rate).quantize(Decimal("0.01"))

    total = subtotal + gst

    return render(
        request,
        "users_panel/cart.html",
        {
            "cart_items": cart_items,
            "cart_count": cart_count,
            "subtotal": subtotal,
            "gst": gst,
            "total": total,
            "has_unavailable_items": has_unavailable_items,
            "save_order_mode": save_order_mode,
            "saved_order_edit_id": saved_order_edit_id,
            "saved_order_edit_name": saved_order_edit_name,
        },
    )


def cart_totals(request):

    session_cart = request.session.get("cart", {})

    products = Product.objects.select_related("category").filter(
        id__in=session_cart.keys()
    )

    subtotal = Decimal("0.00")
    cart_count = 0
    has_unavailable_items = False

    for product in products:

        item = _get_cart_item(session_cart, product.id)

        if not item:
            continue

        quantity = item["quantity"]

        if quantity < 1:
            continue

        quantity = min(quantity, MAX_CART_QUANTITY)

        cart_count += quantity

        if product.is_active and product.category.is_active:
            subtotal += product.price * quantity
        else:
            has_unavailable_items = True

    tax = _get_current_tax()
    tax_percentage = tax.percentage

    tax_rate = tax_percentage / Decimal("100")

    gst = (subtotal * tax_rate).quantize(Decimal("0.01"))

    total = subtotal + gst

    return {
        "cart_count": cart_count,
        "subtotal": str(subtotal),
        "gst": str(gst),
        "total": str(total),
        "has_unavailable_items": has_unavailable_items,
    }


@require_POST
def increase_cart_quantity(request, product_id):

    cart = request.session.get("cart", {})

    product_key = str(product_id)

    item = _get_cart_item(cart, product_id)

    if not item:

        if request.headers.get("x-requested-with") == "XMLHttpRequest":

            return JsonResponse(
                {
                    "success": False,
                    "message": "This item is not in your order.",
                },
                status=404,
            )

        return redirect("cart")

    product = get_object_or_404(
        Product.objects.select_related("category"),
        id=product_id,
    )

    if not product.is_active or not product.category.is_active:

        message = f'"{product.name}" is no longer available.'

        if request.headers.get("x-requested-with") == "XMLHttpRequest":

            return JsonResponse(
                {
                    "success": False,
                    "message": message,
                },
                status=400,
            )

        messages.error(request, message)

        return redirect("cart")

    if item["quantity"] >= MAX_CART_QUANTITY:

        message = f'Maximum quantity for "{product.name}" ' f"is {MAX_CART_QUANTITY}."

        if request.headers.get("x-requested-with") == "XMLHttpRequest":

            return JsonResponse(
                {
                    "success": False,
                    "message": message,
                },
                status=400,
            )

        messages.error(request, message)

        return redirect("cart")

    item["quantity"] += 1

    _save_cart_item(
        cart,
        product.id,
        item["quantity"],
        item["instructions"],
    )

    request.session["cart"] = cart
    request.session.modified = True

    get_qr_table(request, update_activity=True)

    totals = cart_totals(request)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":

        return JsonResponse(
            {
                "success": True,
                "product_id": product.id,
                "quantity": item["quantity"],
                "item_total": str(product.price * item["quantity"]),
                "removed": False,
                **totals,
            }
        )

    return redirect("cart")


@require_POST
def decrease_cart_quantity(request, product_id):

    cart = request.session.get("cart", {})

    item = _get_cart_item(cart, product_id)

    if not item:

        if request.headers.get("x-requested-with") == "XMLHttpRequest":

            return JsonResponse(
                {
                    "success": False,
                    "message": "This item is not in your order.",
                },
                status=404,
            )

        return redirect("cart")

    if item["quantity"] <= 1:

        if request.headers.get("x-requested-with") == "XMLHttpRequest":

            return JsonResponse(
                {
                    "success": False,
                    "message": "Quantity cannot be reduced below 1.",
                },
                status=400,
            )

        return redirect("cart")

    item["quantity"] -= 1

    _save_cart_item(
        cart,
        product_id,
        item["quantity"],
        item["instructions"],
    )

    request.session["cart"] = cart
    request.session.modified = True

    get_qr_table(request, update_activity=True)

    product = get_object_or_404(
        Product.objects.select_related("category"),
        id=product_id,
    )

    item_total = (
        product.price * item["quantity"]
        if (product.is_active and product.category.is_active)
        else Decimal("0.00")
    )

    totals = cart_totals(request)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":

        return JsonResponse(
            {
                "success": True,
                "product_id": product.id,
                "quantity": item["quantity"],
                "item_total": str(item_total),
                "removed": False,
                **totals,
            }
        )

    return redirect("cart")


@require_POST
def remove_from_cart(request, product_id):

    cart = request.session.get("cart", {})

    cart.pop(str(product_id), None)

    request.session["cart"] = cart
    request.session.modified = True

    get_qr_table(request, update_activity=True)

    totals = cart_totals(request)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":

        return JsonResponse(
            {
                "success": True,
                "product_id": product_id,
                "removed": True,
                **totals,
            }
        )

    messages.success(request, "Item removed from your order.")

    return redirect("cart")


@require_POST
def cancel_cart(request):

    request.session.pop("cart", None)

    request.session.pop("save_order_mode", None)

    request.session.pop("saved_order_edit_id", None)

    request.session.pop("saved_order_edit_name", None)

    request.session.modified = True

    get_qr_table(request, update_activity=True)

    messages.success(request, "Your order has been cancelled.")

    return redirect("home")


@login_required(login_url="login")
def product_list(request):

    if not request.user.is_staff:
        return HttpResponseForbidden("You are not authorized to access this page.")

    query = request.GET.get("q", "").strip()
    category_id = request.GET.get("category", "").strip()

    products = (
        Product.objects.select_related("category")
        .prefetch_related("images")
        .order_by("-created_at")
    )

    if query:
        products = products.filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(category__name__icontains=query)
        )

    if category_id:
        products = products.filter(category_id=category_id)

    paginator = Paginator(products, 6)

    page_number = request.GET.get("page")

    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "admin_panel/products.html",
        {
            "page_obj": page_obj,
            "query": query,
            "category_id": category_id,
            "categories": Category.objects.all().order_by("name"),
            "total_products": Product.objects.count(),
            "active_products": Product.objects.filter(is_active=True).count(),
            "today": timezone.localdate(),
        },
    )


@login_required(login_url="login")
def product_detail(request, product_id):

    if not request.user.is_staff:
        return HttpResponseForbidden("You are not authorized to access this page.")

    product = get_object_or_404(
        Product.objects.select_related("category").prefetch_related("images"),
        id=product_id,
    )

    reviews = (
        ReviewRating.objects.filter(product=product)
        .select_related("user", "replied_by")
        .order_by("-created_at", "-id")
    )

    rating_summary = reviews.aggregate(
        average_rating=Avg("rating"), total_reviews=Count("id")
    )

    average_rating = rating_summary["average_rating"] or 0

    total_reviews = rating_summary["total_reviews"]

    review_page_obj = Paginator(reviews, 6).get_page(request.GET.get("reviews_page", 1))

    return render(
        request,
        "admin_panel/product_detail.html",
        {
            "product": product,
            "reviews": review_page_obj.object_list,
            "review_page_obj": review_page_obj,
            "average_rating": average_rating,
            "total_reviews": total_reviews,
        },
    )


TEMP_PRODUCT_IMAGE_DIR = "temporary_product_images"


def get_temp_image_key(request):
    """Get or create a temporary image key for the current session."""

    key = request.session.get("product_temp_upload_key")

    if not key:
        key = uuid.uuid4().hex
        request.session["product_temp_upload_key"] = key

    return key


def save_temp_product_image(request, uploaded_file):
    """Save a cropped image temporarily."""

    key = get_temp_image_key(request)

    filename = f"{uuid.uuid4().hex}.jpg"

    storage_name = f"{TEMP_PRODUCT_IMAGE_DIR}/{key}/{filename}"

    uploaded_file.seek(0)

    return default_storage.save(
        storage_name,
        uploaded_file,
    )


def get_temp_product_image(request, storage_name):
    """Read a temporary image belonging to the current session."""

    key = request.session.get("product_temp_upload_key")

    if not key or not isinstance(storage_name, str):
        return None

    expected_prefix = f"{TEMP_PRODUCT_IMAGE_DIR}/{key}/"

    if not storage_name.startswith(expected_prefix):
        return None

    filename = storage_name[len(expected_prefix) :]

    if not filename or "/" in filename or "\\" in filename or filename in {".", ".."}:
        return None

    if not default_storage.exists(storage_name):
        return None

    with default_storage.open(storage_name, "rb") as stored_file:
        return stored_file.read()


def delete_temp_product_images(storage_names):
    """Delete temporary files after they are no longer needed."""

    for storage_name in storage_names:

        if not isinstance(storage_name, str):
            continue

        if not storage_name.startswith(f"{TEMP_PRODUCT_IMAGE_DIR}/"):
            continue

        default_storage.delete(storage_name)


def get_temp_image_references(request):
    """Read and validate temporary image references from the form."""

    try:
        references = json.loads(request.POST.get("temporary_images", "[]"))
    except (TypeError, json.JSONDecodeError):
        return []

    if not isinstance(references, list):
        return []

    valid_references = []
    seen_fields = set()

    for reference in references:

        if not isinstance(reference, dict):
            continue

        field_name = reference.get("field")
        storage_name = reference.get("storage_name")

        if not isinstance(field_name, str):
            continue

        if not isinstance(storage_name, str):
            continue

        if field_name in seen_fields:
            continue

        if get_temp_product_image(request, storage_name) is None:
            continue

        valid_references.append(
            {
                "field": field_name,
                "storage_name": storage_name,
            }
        )

        seen_fields.add(field_name)

    return valid_references


def restore_temp_product_images(
    request,
    image_formset,
    temporary_references,
):
    """Restore preserved images into their corresponding formset fields."""

    expected_fields = {
        f"{image_formset.prefix}-{index}-image"
        for index in range(image_formset.total_form_count())
    }

    restored_fields = set()

    for reference in temporary_references:
        field_name = reference["field"]
        storage_name = reference["storage_name"]

        if field_name not in expected_fields:
            continue

        # Keep a newly uploaded file if one exists.
        uploaded_file = request.FILES.get(field_name)

        if uploaded_file and uploaded_file.size > 0:
            continue

        image_bytes = get_temp_product_image(
            request,
            storage_name,
        )

        if image_bytes is None:
            continue

        request.FILES[field_name] = SimpleUploadedFile(
            name="preserved_product_image.jpg",
            content=image_bytes,
            content_type="image/jpeg",
        )

        restored_fields.add(field_name)

    return restored_fields


def preserve_temp_product_images(
    request,
    image_formset,
    existing_references,
    newly_uploaded_fields,
):
    """
    Preserve newly uploaded images and retain existing temporary images.

    Images already restored from temporary storage are not saved again.
    """

    references_by_field = {
        reference["field"]: reference["storage_name"]
        for reference in existing_references
    }

    new_references = []
    files_to_delete = []

    for index, image_form in enumerate(image_formset):

        field_name = f"{image_formset.prefix}-{index}-image"

        old_reference = references_by_field.get(field_name)

        # Do not retain temporary images explicitly marked for deletion.
        if (
            image_form.cleaned_data.get("DELETE")
            if image_form.is_bound and image_form.is_valid()
            else False
        ):
            if old_reference:
                files_to_delete.append(old_reference)

            continue

        uploaded_file = request.FILES.get(field_name)

        if field_name in newly_uploaded_fields and uploaded_file:

            new_storage_name = save_temp_product_image(
                request,
                uploaded_file,
            )

            new_references.append(
                {
                    "field": field_name,
                    "storage_name": new_storage_name,
                }
            )

            if old_reference:
                files_to_delete.append(old_reference)

        elif old_reference:

            new_references.append(
                {
                    "field": field_name,
                    "storage_name": old_reference,
                }
            )

    delete_temp_product_images(files_to_delete)

    return new_references


@login_required(login_url="login")
def temporary_product_image_preview(request):

    if not request.user.is_staff:
        return HttpResponseForbidden("You are not authorized to access this image.")

    storage_name = request.GET.get("name", "")

    image_bytes = get_temp_product_image(
        request,
        storage_name,
    )

    if image_bytes is None:
        raise Http404

    return HttpResponse(
        image_bytes,
        content_type="image/jpeg",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@login_required(login_url="login")
def add_product(request):

    if not request.user.is_staff:
        return HttpResponseForbidden("You are not authorized to access this page.")

    temporary_references = []

    if request.method == "POST":

        temporary_references = get_temp_image_references(request)

        form = ProductForm(request.POST)

        image_formset = ProductImageFormSet(
            request.POST,
            request.FILES,
        )

        # Record which files were genuinely uploaded in this request.
        newly_uploaded_fields = {
            field_name for field_name in request.FILES if field_name.endswith("-image")
        }

        restore_temp_product_images(
            request,
            image_formset,
            temporary_references,
        )

        image_formset = ProductImageFormSet(
            request.POST,
            request.FILES,
        )

        form_valid = form.is_valid()
        images_valid = image_formset.is_valid()

        if form_valid and images_valid:

            image_count = sum(
                1
                for image_form in image_formset
                if image_form.cleaned_data.get("image")
                and not image_form.cleaned_data.get("DELETE")
            )

            if image_count < 3:

                messages.error(
                    request,
                    "A product must have at least 3 images.",
                )

            else:

                product = form.save()

                image_formset.instance = product
                image_formset.save()

                delete_temp_product_images(
                    [reference["storage_name"] for reference in temporary_references]
                )

                messages.success(
                    request,
                    "Product added successfully.",
                )

                return redirect("product_list")

        temporary_references = preserve_temp_product_images(
            request,
            image_formset,
            temporary_references,
            newly_uploaded_fields,
        )

    else:

        form = ProductForm()
        image_formset = ProductImageFormSet()

    return render(
        request,
        "admin_panel/product_form.html",
        {
            "form": form,
            "image_formset": image_formset,
            "page_title": "Add Product",
            "button_text": "Add Product",
            "temporary_references_json": json.dumps(temporary_references),
        },
    )


@login_required(login_url="login")
@require_POST
def toggle_product_status(request, product_id):

    if not request.user.is_staff:
        return HttpResponseForbidden("You are not authorized to perform this action.")

    product = get_object_or_404(Product, id=product_id)

    if not product.is_active and not product.category.is_active:

        messages.error(
            request,
            f'"{product.name}" cannot be made available because its category is inactive.',
        )

        return redirect("product_list")

    product.is_active = not product.is_active

    product.save(update_fields=["is_active", "updated_at"])

    if product.is_active:

        messages.success(request, f'"{product.name}" is now available.')

    else:

        messages.warning(request, f'"{product.name}" is now unavailable.')

    return redirect("product_list")


@login_required(login_url="login")
def edit_product(request, product_id):

    if not request.user.is_staff:
        return HttpResponseForbidden("You are not authorized to access this page.")

    product = get_object_or_404(
        Product,
        id=product_id,
    )

    temporary_references = []

    if request.method == "POST":

        temporary_references = get_temp_image_references(request)

        form = ProductForm(
            request.POST,
            instance=product,
        )

        image_formset = ProductImageFormSet(
            request.POST,
            request.FILES,
            instance=product,
        )

        newly_uploaded_fields = {
            field_name for field_name in request.FILES if field_name.endswith("-image")
        }

        restore_temp_product_images(
            request,
            image_formset,
            temporary_references,
        )

        image_formset = ProductImageFormSet(
            request.POST,
            request.FILES,
            instance=product,
        )

        form_valid = form.is_valid()
        images_valid = image_formset.is_valid()

        if form_valid and images_valid:

            existing_images = product.images.count()

            deleted_images = sum(
                1
                for image_form in image_formset
                if image_form.instance.pk and image_form.cleaned_data.get("DELETE")
            )

            new_images = sum(
                1
                for image_form in image_formset
                if not image_form.instance.pk
                and image_form.cleaned_data.get("image")
                and not image_form.cleaned_data.get("DELETE")
            )

            final_image_count = existing_images - deleted_images + new_images

            if final_image_count < 3:

                messages.error(
                    request,
                    "A product must have at least 3 images.",
                )

            else:

                form.save()
                image_formset.save()

                delete_temp_product_images(
                    [reference["storage_name"] for reference in temporary_references]
                )

                messages.success(
                    request,
                    "Product updated successfully.",
                )

                return redirect("product_list")

        temporary_references = preserve_temp_product_images(
            request,
            image_formset,
            temporary_references,
            newly_uploaded_fields,
        )

    else:

        form = ProductForm(instance=product)

        image_formset = ProductImageFormSet(
            instance=product,
        )

    return render(
        request,
        "admin_panel/product_form.html",
        {
            "form": form,
            "image_formset": image_formset,
            "product": product,
            "page_title": "Edit Product",
            "button_text": "Save Changes",
            "temporary_references_json": json.dumps(temporary_references),
        },
    )
