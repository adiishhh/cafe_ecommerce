from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.core.paginator import Paginator
from django.db.models import Q
from django.contrib import messages
from django.views.decorators.http import require_POST
from .forms import ProductForm, ProductImageFormSet
from .models import Product
from category.models import Category
from decimal import Decimal, InvalidOperation


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
        15
    )

    page_number = request.GET.get('page')

    page_obj = paginator.get_page(
        page_number
    )

    categories = Category.objects.filter(
        is_active=True
    ).order_by('name')

    cart = request.session.get('cart', {})

    cart_count = sum(
        cart.values()
    )

    cart_total = Decimal('0.00')

    if cart:

        cart_products = Product.objects.filter(
            id__in=cart.keys(),
            is_active=True,
            category__is_active=True
        )

        for product in cart_products:
            cart_total += product.price * cart.get(
                str(product.id),
                0
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
        Product.objects.select_related(
            'category'
        ).prefetch_related(
            'images'
        ),
        id=product_id
    )

    related_products = Product.objects.select_related(
        'category'
    ).prefetch_related(
        'images'
    ).filter(
        category=product.category
    ).exclude(
        id=product.id
    ).order_by(
        '-created_at'
    )[:12]

    return render(
        request,
        'users_panel/product_detail.html',
        {
            'product': product,
            'related_products': related_products,
        }
    )

MAX_CART_QUANTITY = 10

@require_POST
def add_to_cart(request, product_id):

    product = get_object_or_404(
        Product.objects.select_related('category'),
        id=product_id
    )

    if not product.is_active or not product.category.is_active:

        messages.error(
            request,
            'This product is currently unavailable.'
        )

        return redirect('home')

    try:
        quantity = int(
            request.POST.get('quantity', 1)
        )

    except (TypeError, ValueError):
        quantity = 1

    if quantity < 1:
        quantity = 1

    if quantity > MAX_CART_QUANTITY:
        messages.error(
            request,
            f'You can add a maximum of {MAX_CART_QUANTITY} of this product.'
        )

        return redirect(
            'customer_product_detail',
            product_id=product.id
        )

    cart = request.session.get(
        'cart',
        {}
    )

    product_key = str(product.id)

    current_quantity = cart.get(
        product_key,
        0
    )

    new_quantity = current_quantity + quantity

    if new_quantity > MAX_CART_QUANTITY:

        messages.error(
            request,
            f'Maximum quantity for "{product.name}" is {MAX_CART_QUANTITY}.'
        )

        return redirect(
            'customer_product_detail',
            product_id=product.id
        )

    cart[product_key] = new_quantity

    request.session['cart'] = cart
    request.session.modified = True

    messages.success(
        request,
        f'{product.name} added to your order.'
    )

    return redirect('home')

def cart(request):

    session_cart = request.session.get(
        'cart',
        {}
    )

    if not session_cart:

        return render(
            request,
            'users_panel/cart.html',
            {
                'cart_items': [],
                'cart_count': 0,
                'subtotal': Decimal('0.00'),
                'gst': Decimal('0.00'),
                'total': Decimal('0.00'),
                'has_unavailable_items': False,
            }
        )

    products = Product.objects.select_related(
        'category'
    ).prefetch_related(
        'images'
    ).filter(
        id__in=session_cart.keys()
    )

    cart_items = []

    subtotal = Decimal('0.00')
    cart_count = 0
    has_unavailable_items = False

    for product in products:

        quantity = session_cart.get(
            str(product.id),
            0
        )

        if quantity < 1:
            continue

        if quantity > MAX_CART_QUANTITY:
            quantity = MAX_CART_QUANTITY

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

            item_total = Decimal('0.00')

            has_unavailable_items = True

        cart_count += quantity

        cart_items.append(
            {
                'product': product,
                'quantity': quantity,
                'item_total': item_total,
                'is_available': is_available,
            }
        )

    gst = (
        subtotal * Decimal('0.05')
    ).quantize(
        Decimal('0.01')
    )

    total = subtotal + gst

    return render(
        request,
        'users_panel/cart.html',
        {
            'cart_items': cart_items,
            'cart_count': cart_count,
            'subtotal': subtotal,
            'gst': gst,
            'total': total,
            'has_unavailable_items': has_unavailable_items,
        }
    )

def cart_totals(request):
    session_cart = request.session.get('cart', {})

    products = Product.objects.select_related(
        'category'
    ).filter(
        id__in=session_cart.keys()
    )

    subtotal = Decimal('0.00')
    cart_count = 0
    has_unavailable_items = False

    for product in products:
        quantity = session_cart.get(str(product.id), 0)

        if quantity < 1:
            continue

        quantity = min(quantity, MAX_CART_QUANTITY)

        cart_count += quantity

        if product.is_active and product.category.is_active:
            subtotal += product.price * quantity
        else:
            has_unavailable_items = True

    gst = (subtotal * Decimal('0.05')).quantize(
        Decimal('0.01')
    )

    total = subtotal + gst

    return {
        'cart_count': cart_count,
        'subtotal': str(subtotal),
        'gst': str(gst),
        'total': str(total),
        'has_unavailable_items': has_unavailable_items,
    }

@require_POST
def increase_cart_quantity(request, product_id):
    cart = request.session.get('cart', {})
    product_key = str(product_id)

    if product_key not in cart:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    'success': False,
                    'message': 'This item is not in your order.'
                },
                status=404
            )

        return redirect('cart')

    product = get_object_or_404(
        Product.objects.select_related('category'),
        id=product_id
    )

    if not product.is_active or not product.category.is_active:
        message = f'"{product.name}" is no longer available.'

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    'success': False,
                    'message': message
                },
                status=400
            )

        messages.error(request, message)
        return redirect('cart')

    if cart[product_key] >= MAX_CART_QUANTITY:
        message = (
            f'Maximum quantity for "{product.name}" '
            f'is {MAX_CART_QUANTITY}.'
        )

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    'success': False,
                    'message': message
                },
                status=400
            )

        messages.error(request, message)
        return redirect('cart')

    cart[product_key] += 1

    request.session['cart'] = cart
    request.session.modified = True

    totals = cart_totals(request)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse(
            {
                'success': True,
                'product_id': product.id,
                'quantity': cart[product_key],
                'item_total': str(
                    product.price * cart[product_key]
                ),
                **totals,
            }
        )

    return redirect('cart')

@require_POST
def decrease_cart_quantity(request, product_id):
    cart = request.session.get('cart', {})
    product_key = str(product_id)

    if product_key not in cart:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    'success': False,
                    'message': 'This item is not in your order.'
                },
                status=404
            )

        return redirect('cart')

    if cart[product_key] <= 1:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    'success': False,
                    'message': 'Quantity cannot be reduced below 1.'
                },
                status=400
            )

        return redirect('cart')

    cart[product_key] -= 1

    request.session['cart'] = cart
    request.session.modified = True

    product = get_object_or_404(
        Product.objects.select_related('category'),
        id=product_id
    )

    item_total = (
        product.price * cart[product_key]
        if product.is_active and product.category.is_active
        else Decimal('0.00')
    )

    totals = cart_totals(request)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse(
            {
                'success': True,
                'product_id': product.id,
                'quantity': cart[product_key],
                'item_total': str(item_total),
                'removed': False,
                **totals,
            }
        )

    return redirect('cart')

@require_POST
def remove_from_cart(request, product_id):
    cart = request.session.get('cart', {})
    product_key = str(product_id)

    cart.pop(product_key, None)

    request.session['cart'] = cart
    request.session.modified = True

    totals = cart_totals(request)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse(
            {
                'success': True,
                'product_id': product_id,
                'removed': True,
                **totals,
            }
        )

    messages.success(
        request,
        'Item removed from your order.'
    )

    return redirect('cart')

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

    return render(
        request,
        'admin_panel/product_detail.html',
        {
            'product': product,
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