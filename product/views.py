from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from .models import Product
from category.models import Category
from decimal import Decimal, InvalidOperation
from .forms import ProductForm, ProductImageFormSet

# Create your views here.

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
    ).filter(
        category__is_active=True
    )

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
        6
    )

    page_number = request.GET.get('page')

    page_obj = paginator.get_page(
        page_number
    )

    categories = Category.objects.filter(
        is_active=True
    ).order_by('name')

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
        }
    )

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

    paginator = Paginator(products, 6)

    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

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
        Product.objects.select_related('category').prefetch_related('images'),
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
