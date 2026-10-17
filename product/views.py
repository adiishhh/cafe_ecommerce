from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.core.paginator import Paginator
from django.db.models import Q
from django.contrib import messages
from django.views.decorators.http import require_POST
from .forms import ProductForm, ProductImageFormSet
from .models import Product
from orders.models import Tax
from category.models import Category
from decimal import Decimal, InvalidOperation
from django.db.models import Avg, Count
from django.utils import timezone
from .models import ReviewRating
from django.http import HttpResponseBadRequest

def _get_current_tax():
    tax = Tax.objects.first()

    if tax is None:
        tax = Tax.objects.create(
            percentage=Decimal("5.00")
        )

    return tax

def customer_home(request):

    if request.user.is_staff:
        return redirect('admin_users')

    query = request.GET.get('q', '').strip()
    category_id = request.GET.get('category', '').strip()
    sort = request.GET.get('sort', '').strip()
    min_price = request.GET.get('min_price', '').strip()
    max_price = request.GET.get('max_price', '').strip()

    products = Product.objects.select_related(
        'category'
    ).prefetch_related(
        'images'
    ).all()

    if query:
        products = products.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query) |
            Q(category__name__icontains=query)
        )

    if category_id:
        products = products.filter(
            category_id=category_id
        )

    if min_price:
        try:
            min_price_value = Decimal(min_price)

            if min_price_value >= 0:
                products = products.filter(
                    price__gte=min_price_value
                )
            else:
                min_price = ''

        except (InvalidOperation, ValueError):
            min_price = ''

    if max_price:
        try:
            max_price_value = Decimal(max_price)

            if max_price_value >= 0:
                products = products.filter(
                    price__lte=max_price_value
                )
            else:
                max_price = ''

        except (InvalidOperation, ValueError):
            max_price = ''

    if sort == 'price_low':

        products = products.order_by('price')

    elif sort == 'price_high':

        products = products.order_by('-price')

    elif sort == 'name_az':

        products = products.order_by('name')

    elif sort == 'name_za':

        products = products.order_by('-name')

    else:

        products = products.order_by('-created_at')

    paginator = Paginator(
        products,
        16
    )

    page_number = request.GET.get('page')

    page_obj = paginator.get_page(
        page_number
    )

    categories = Category.objects.filter(
        is_active=True
    ).order_by('name')

    cart = request.session.get('cart', {})

    cart_count = 0
    cart_total = Decimal('0.00')

    if cart:

        cart_products = Product.objects.filter(
            id__in=cart.keys(),
            is_active=True,
            category__is_active=True
        )

        for product in cart_products:
            item = cart.get(
                str(product.id),
                {}
            )

            if isinstance(item, int):
                quantity = item
            else:
                quantity = int(
                    item.get("quantity", 0)
                )

            cart_count += quantity

            cart_total += (
                product.price * quantity
            )

    return render(
        request,
        'users_panel/home.html',
        {
            'page_obj': page_obj,
            'categories': categories,
            'query': query,
            'category_id': category_id,
            'sort': sort,
            'min_price': min_price,
            'max_price': max_price,
            'cart_count': cart_count,
            'cart_total': cart_total,
        }
    )

def customer_product_detail(request, product_id):
    product = get_object_or_404(
        Product.objects.select_related("category").prefetch_related("images"),
        id=product_id
    )

    reviews = (
        ReviewRating.objects
        .filter(product=product)
        .select_related("user", "replied_by")
        .order_by("-created_at", "-id")
    )

    rating_summary = reviews.aggregate(
        average_rating=Avg("rating"),
        total_reviews=Count("id")
    )

    average_rating = rating_summary["average_rating"] or 0
    total_reviews = rating_summary["total_reviews"]

    user_review = None

    if request.user.is_authenticated and not request.user.is_staff:
        user_review = ReviewRating.objects.filter(
            product=product,
            user=request.user
        ).first()

    related_products_queryset = (
        Product.objects
        .select_related("category")
        .prefetch_related("images")
        .filter(category=product.category)
        .exclude(id=product.id)
        .order_by("-created_at", "-id")
    )

    related_products_count = related_products_queryset.count()

    related_products = list(
        related_products_queryset[:4]
    )

    related_page = 0
    has_previous_related = False
    has_next_related = related_products_count > 4

    first_review = reviews.first()

    displayed_reviews = (
        [first_review]
        if first_review is not None
        else []
    )

    review = first_review
    review_index = 0

    has_previous_review = False
    has_next_review = total_reviews > 1

    is_ajax = (
        request.headers.get("X-Requested-With")
        == "XMLHttpRequest"
    )

    section = request.GET.get("section")

    if is_ajax and section == "related_products":

        try:
            related_page = int(
                request.GET.get("page", 0)
            )
        except (TypeError, ValueError):
            return HttpResponseBadRequest(
                "Invalid related-products page."
            )

        if related_page < 0:
            return HttpResponseBadRequest(
                "Invalid related-products page."
            )

        start = related_page * 4
        end = start + 4

        related_products = list(
            related_products_queryset[start:end]
        )

        if related_page > 0 and not related_products:
            return HttpResponseBadRequest(
                "No related products found for this page."
            )

        has_previous_related = related_page > 0
        has_next_related = end < related_products_count

    elif is_ajax and section == "reviews":

        try:
            review_index = int(
                request.GET.get("index", 0)
            )
        except (TypeError, ValueError):
            return HttpResponseBadRequest(
                "Invalid review index."
            )

        if review_index < 0 or review_index >= total_reviews:
            return HttpResponseBadRequest(
                "Invalid review index."
            )

        review = reviews[
            review_index:review_index + 1
        ].first()

        if review is None:
            return HttpResponseBadRequest(
                "Review not found."
            )

        displayed_reviews = [review]

        has_previous_review = review_index > 0
        has_next_review = review_index < total_reviews - 1

    elif is_ajax:
        return HttpResponseBadRequest(
            "Invalid AJAX section."
        )

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

    return render(
        request,
        "users_panel/product_detail.html",
        context
    )

@login_required(login_url="login")
@require_POST
def submit_product_review(request, product_id):

    if request.user.is_staff:
        return HttpResponseForbidden(
            "Administrators cannot submit customer reviews."
        )

    product = get_object_or_404(
        Product.objects.select_related("category"),
        id=product_id
    )

    if not product.is_active or not product.category.is_active:

        messages.error(
            request,
            "You cannot review an unavailable product."
        )

        return redirect(
            "customer_product_detail",
            product_id=product.id
        )

    rating_value = request.POST.get(
        "rating", ""
    ).strip()

    review_text = request.POST.get(
        "review", ""
    ).strip()

    try:
        rating_value = int(rating_value)
    except (TypeError, ValueError):
        rating_value = 0

    if rating_value not in range(1, 6):

        messages.error(
            request,
            "Please select a rating between 1 and 5 stars."
        )

        return redirect(
            "customer_product_detail",
            product_id=product.id
        )

    if not review_text:

        messages.error(
            request,
            "Please enter your review."
        )

        return redirect(
            "customer_product_detail",
            product_id=product.id
        )

    if len(review_text) > 2000:

        messages.error(
            request,
            "Your review cannot exceed 2000 characters."
        )

        return redirect(
            "customer_product_detail",
            product_id=product.id
        )

    review_obj, created = ReviewRating.objects.get_or_create(
        product=product,
        user=request.user,
        defaults={
            "rating": rating_value,
            "review": review_text,
        }
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

        messages.success(
            request,
            "Your review has been updated."
        )

    else:

        messages.success(
            request,
            "Thank you! Your review has been submitted."
        )

    return redirect(
        "customer_product_detail",
        product_id=product.id
    )

@login_required(login_url="login")
@require_POST
def delete_product_review(request, product_id):

    if request.user.is_staff:
        return HttpResponseForbidden(
            "Administrators cannot use this customer action."
        )

    review = get_object_or_404(
        ReviewRating,
        product_id=product_id,
        user=request.user
    )

    review.delete()

    messages.success(
        request,
        "Your review has been deleted."
    )

    return redirect(
        "customer_product_detail",
        product_id=product_id
    )

@login_required(login_url="login")
@require_POST
def admin_review_reply(request, review_id):

    if not request.user.is_staff:
        return HttpResponseForbidden(
            "You are not authorized to reply to reviews."
        )

    review_obj = get_object_or_404(
        ReviewRating.objects.select_related("product"),
        id=review_id
    )

    reply_text = request.POST.get(
        "admin_reply", ""
    ).strip()

    if not reply_text:

        messages.error(
            request,
            "Please enter a reply before submitting."
        )

        return redirect(
            "product_detail",
            product_id=review_obj.product_id
        )

    if len(reply_text) > 2000:

        messages.error(
            request,
            "The reply cannot exceed 2000 characters."
        )

        return redirect(
            "product_detail",
            product_id=review_obj.product_id
        )

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

    messages.success(
        request,
        "Your reply has been saved."
    )

    return redirect(
        "product_detail",
        product_id=review_obj.product_id
    )

@login_required(login_url="login")
@require_POST
def admin_delete_review_reply(request, review_id):

    if not request.user.is_staff:
        return HttpResponseForbidden(
            "You are not authorized to delete review replies."
        )

    review_obj = get_object_or_404(
        ReviewRating.objects.select_related("product"),
        id=review_id
    )

    if not review_obj.admin_reply:

        messages.info(
            request,
            "This review does not have a reply to delete."
        )

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

        messages.success(
            request,
            "Administrator reply deleted successfully."
        )

    return redirect(
        "product_detail",
        product_id=review_obj.product_id
    )

@login_required(login_url="login")
@require_POST
def admin_delete_product_review(request, review_id):

    if not request.user.is_staff:
        return HttpResponseForbidden(
            "You are not authorized to delete customer reviews."
        )

    review_obj = get_object_or_404(
        ReviewRating.objects.select_related("product"),
        id=review_id
    )

    product_id = review_obj.product_id

    review_obj.delete()

    messages.success(
        request,
        "Customer review deleted successfully."
    )

    return redirect(
        "product_detail",
        product_id=product_id
    )

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

        messages.error(
            request,
            "This product is currently unavailable."
        )

        return redirect(
            "customer_product_detail",
            product_id=product.id,
        )

    try:
        quantity = int(
            request.POST.get("quantity", 1)
        )
    except (TypeError, ValueError):
        quantity = 1

    if quantity < 1:
        quantity = 1

    if quantity > MAX_CART_QUANTITY:

        messages.error(
            request,
            f"You can add a maximum of {MAX_CART_QUANTITY} of this product."
        )

        return redirect(
            "customer_product_detail",
            product_id=product.id,
        )

    instructions = request.POST.get(
        "instructions",
        ""
    ).strip()

    cart = request.session.get(
        "cart",
        {}
    )

    product_key = str(product.id)

    existing_item = _get_cart_item(
        cart,
        product.id
    )

    current_quantity = (
        existing_item["quantity"]
        if existing_item
        else 0
    )

    new_quantity = current_quantity + quantity

    if new_quantity > MAX_CART_QUANTITY:

        messages.error(
            request,
            f'Maximum quantity for "{product.name}" '
            f'is {MAX_CART_QUANTITY}.'
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

    if request.session.get("save_order_mode"):

        messages.success(
            request,
            f"{product.name} added to your usual."
        )

    else:

        messages.success(
            request,
            f"{product.name} added to your order."
        )

    return redirect("home")


def cart(request):

    session_cart = request.session.get(
        "cart",
        {}
    )

    save_order_mode = request.session.get(
        "save_order_mode",
        False,
    )

    saved_order_edit_id = request.session.get(
        "saved_order_edit_id"
    )

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
    has_unavailable_items = False

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

        instructions = item["instructions"]

        is_available = (
            product.is_active
            and product.category.is_active
        )

        if is_available:

            item_total = (
                product.price * quantity
            )

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

    gst = (
        subtotal * tax_rate
    ).quantize(
        Decimal("0.01")
    )

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

    session_cart = request.session.get(
        "cart",
        {}
    )

    products = Product.objects.select_related(
        "category"
    ).filter(
        id__in=session_cart.keys()
    )

    subtotal = Decimal("0.00")
    cart_count = 0
    has_unavailable_items = False

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

        cart_count += quantity

        if (
            product.is_active
            and product.category.is_active
        ):
            subtotal += (
                product.price * quantity
            )
        else:
            has_unavailable_items = True

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
        "cart_count": cart_count,
        "subtotal": str(subtotal),
        "gst": str(gst),
        "total": str(total),
        "has_unavailable_items": has_unavailable_items,
    }


@require_POST
def increase_cart_quantity(request, product_id):

    cart = request.session.get(
        "cart",
        {}
    )

    product_key = str(product_id)

    item = _get_cart_item(
        cart,
        product_id
    )

    if not item:

        if request.headers.get(
            "x-requested-with"
        ) == "XMLHttpRequest":

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

        message = (
            f'"{product.name}" is no longer available.'
        )

        if request.headers.get(
            "x-requested-with"
        ) == "XMLHttpRequest":

            return JsonResponse(
                {
                    "success": False,
                    "message": message,
                },
                status=400,
            )

        messages.error(
            request,
            message
        )

        return redirect("cart")

    if item["quantity"] >= MAX_CART_QUANTITY:

        message = (
            f'Maximum quantity for "{product.name}" '
            f"is {MAX_CART_QUANTITY}."
        )

        if request.headers.get(
            "x-requested-with"
        ) == "XMLHttpRequest":

            return JsonResponse(
                {
                    "success": False,
                    "message": message,
                },
                status=400,
            )

        messages.error(
            request,
            message
        )

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

    totals = cart_totals(request)

    if request.headers.get(
        "x-requested-with"
    ) == "XMLHttpRequest":

        return JsonResponse(
            {
                "success": True,
                "product_id": product.id,
                "quantity": item["quantity"],
                "item_total": str(
                    product.price * item["quantity"]
                ),
                "removed": False,
                **totals,
            }
        )

    return redirect("cart")


@require_POST
def decrease_cart_quantity(request, product_id):

    cart = request.session.get(
        "cart",
        {}
    )

    item = _get_cart_item(
        cart,
        product_id
    )

    if not item:

        if request.headers.get(
            "x-requested-with"
        ) == "XMLHttpRequest":

            return JsonResponse(
                {
                    "success": False,
                    "message": "This item is not in your order.",
                },
                status=404,
            )

        return redirect("cart")

    if item["quantity"] <= 1:

        if request.headers.get(
            "x-requested-with"
        ) == "XMLHttpRequest":

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

    product = get_object_or_404(
        Product.objects.select_related("category"),
        id=product_id,
    )

    item_total = (
        product.price * item["quantity"]
        if (
            product.is_active
            and product.category.is_active
        )
        else Decimal("0.00")
    )

    totals = cart_totals(request)

    if request.headers.get(
        "x-requested-with"
    ) == "XMLHttpRequest":

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

    cart = request.session.get(
        "cart",
        {}
    )

    cart.pop(
        str(product_id),
        None
    )

    request.session["cart"] = cart
    request.session.modified = True

    totals = cart_totals(request)

    if request.headers.get(
        "x-requested-with"
    ) == "XMLHttpRequest":

        return JsonResponse(
            {
                "success": True,
                "product_id": product_id,
                "removed": True,
                **totals,
            }
        )

    messages.success(
        request,
        "Item removed from your order."
    )

    return redirect("cart")


@require_POST
def cancel_cart(request):

    request.session.pop(
        "cart",
        None
    )

    request.session.pop(
        "save_order_mode",
        None
    )

    request.session.pop(
        "saved_order_edit_id",
        None
    )

    request.session.pop(
        "saved_order_edit_name",
        None
    )

    request.session.modified = True

    messages.success(
        request,
        "Your order has been cancelled."
    )

    return redirect("home")

@login_required(login_url='login')
def product_list(request):

    if not request.user.is_staff:
        return HttpResponseForbidden(
            'You are not authorized to access this page.'
        )

    query = request.GET.get('q', '').strip()
    category_id = request.GET.get('category', '').strip()

    products = Product.objects.select_related(
        'category'
    ).prefetch_related(
        'images'
    ).order_by('-created_at')

    if query:
        products = products.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query) |
            Q(category__name__icontains=query)
        )

    if category_id:
        products = products.filter(
            category_id=category_id
        )

    paginator = Paginator(
        products,
        6
    )

    page_number = request.GET.get('page')

    page_obj = paginator.get_page(
        page_number
    )

    return render(
        request,
        'admin_panel/products.html',
        {
            'page_obj': page_obj,
            'query': query,
            'category_id': category_id,
            'categories': Category.objects.all().order_by('name'),
            'total_products': Product.objects.count(),
            'active_products': Product.objects.filter(
                is_active=True
            ).count(),
        }
    )


@login_required(login_url='login')
def product_detail(request, product_id):

    if not request.user.is_staff:
        return HttpResponseForbidden(
            'You are not authorized to access this page.'
        )

    product = get_object_or_404(
        Product.objects.select_related(
            'category'
        ).prefetch_related(
            'images'
        ),
        id=product_id
    )

    reviews = ReviewRating.objects.filter(
        product=product
    ).select_related(
        'user',
        'replied_by'
    ).order_by(
        '-created_at',
        '-id'
    )

    rating_summary = reviews.aggregate(
        average_rating=Avg('rating'),
        total_reviews=Count('id')
    )

    average_rating = (
        rating_summary['average_rating'] or 0
    )

    total_reviews = rating_summary['total_reviews']

    review_page_obj = Paginator(
        reviews,
        6
    ).get_page(
        request.GET.get('reviews_page', 1)
    )

    return render(
        request,
        'admin_panel/product_detail.html',
        {
            'product': product,
            'reviews': review_page_obj.object_list,
            'review_page_obj': review_page_obj,
            'average_rating': average_rating,
            'total_reviews': total_reviews,
        }
    )

@login_required(login_url='login')
def add_product(request):

    if not request.user.is_staff:
        return HttpResponseForbidden(
            'You are not authorized to access this page.'
        )

    if request.method == 'POST':

        form = ProductForm(request.POST)

        image_formset = ProductImageFormSet(
            request.POST,
            request.FILES
        )

        if form.is_valid() and image_formset.is_valid():

            image_count = sum(
                1
                for image_form in image_formset
                if image_form.cleaned_data.get('image')
            )

            if image_count < 3:

                messages.error(
                    request,
                    'A product must have at least 3 images.'
                )

            else:

                product = form.save()

                image_formset.instance = product
                image_formset.save()

                messages.success(
                    request,
                    'Product added successfully.'
                )

                return redirect('product_list')

    else:

        form = ProductForm()

        image_formset = ProductImageFormSet()

    return render(
        request,
        'admin_panel/product_form.html',
        {
            'form': form,
            'image_formset': image_formset,
            'page_title': 'Add Product',
            'button_text': 'Add Product',
        }
    )


@login_required(login_url='login')
@require_POST
def toggle_product_status(request, product_id):

    if not request.user.is_staff:
        return HttpResponseForbidden(
            'You are not authorized to perform this action.'
        )

    product = get_object_or_404(
        Product,
        id=product_id
    )

    if not product.is_active and not product.category.is_active:

        messages.error(
            request,
            f'"{product.name}" cannot be made available because its category is inactive.'
        )

        return redirect('product_list')

    product.is_active = not product.is_active

    product.save(
        update_fields=[
            'is_active',
            'updated_at'
        ]
    )

    if product.is_active:

        messages.success(
            request,
            f'"{product.name}" is now available.'
        )

    else:

        messages.warning(
            request,
            f'"{product.name}" is now unavailable.'
        )

    return redirect('product_list')


@login_required(login_url='login')
def edit_product(request, product_id):

    if not request.user.is_staff:
        return HttpResponseForbidden(
            'You are not authorized to access this page.'
        )

    product = get_object_or_404(
        Product,
        id=product_id
    )

    if request.method == 'POST':

        form = ProductForm(
            request.POST,
            instance=product
        )

        image_formset = ProductImageFormSet(
            request.POST,
            request.FILES,
            instance=product
        )

        if form.is_valid() and image_formset.is_valid():

            existing_images = product.images.count()

            deleted_images = sum(
                1
                for image_form in image_formset
                if image_form.instance.pk
                and image_form.cleaned_data.get('DELETE')
            )

            new_images = sum(
                1
                for image_form in image_formset
                if not image_form.instance.pk
                and image_form.cleaned_data.get('image')
            )

            final_image_count = (
                existing_images
                - deleted_images
                + new_images
            )

            if final_image_count < 3:

                messages.error(
                    request,
                    'A product must have at least 3 images.'
                )

            else:

                form.save()

                image_formset.save()

                messages.success(
                    request,
                    'Product updated successfully.'
                )

                return redirect('product_list')

    else:

        form = ProductForm(
            instance=product
        )

        image_formset = ProductImageFormSet(
            instance=product
        )

    return render(
        request,
        'admin_panel/product_form.html',
        {
            'form': form,
            'image_formset': image_formset,
            'product': product,
            'page_title': 'Edit Product',
            'button_text': 'Save Changes',
        }
    )