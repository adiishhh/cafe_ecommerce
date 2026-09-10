from .models import Category
from django.shortcuts import render
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from .forms import CategoryForm

# Create your views here.

@login_required(login_url='login')
def category_list(request):
    if not request.user.is_staff:
        return HttpResponseForbidden(
            'You are not authorized to access this page.'
        )

    query = request.GET.get('q', '').strip()

    categories = Category.objects.all().order_by('-created_at')

    if query:
        categories = categories.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query)
        )

    paginator = Paginator(categories, 6)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        'admin_panel/categories.html',
        {
            'page_obj': page_obj,
            'query': query,
            'total_categories': Category.objects.count(),
            'active_categories': Category.objects.filter(
                is_active=True
            ).count(),
        }
    )


@login_required(login_url='login')
def add_category(request):
    if not request.user.is_staff:
        return HttpResponseForbidden(
            'You are not authorized to access this page.'
        )

    if request.method == 'POST':
        form = CategoryForm(request.POST)

        if form.is_valid():
            form.save()

            messages.success(
                request,
                'Category added successfully.'
            )

            return redirect('category_list')

    else:
        form = CategoryForm()

    return render(
        request,
        'admin_panel/category_form.html',
        {
            'form': form,
            'page_title': 'Add Category',
            'button_text': 'Add Category',
        }
    )


@login_required(login_url='login')
def edit_category(request, category_id):
    if not request.user.is_staff:
        return HttpResponseForbidden(
            'You are not authorized to access this page.'
        )

    category = get_object_or_404(
        Category,
        id=category_id
    )

    if request.method == 'POST':
        form = CategoryForm(
            request.POST,
            instance=category
        )

        if form.is_valid():
            form.save()

            messages.success(
                request,
                'Category updated successfully.'
            )

            return redirect('category_list')

    else:
        form = CategoryForm(instance=category)

    return render(
        request,
        'admin_panel/category_form.html',
        {
            'form': form,
            'category': category,
            'page_title': 'Edit Category',
            'button_text': 'Save Changes',
        }
    )


@login_required(login_url='login')
@require_POST
def toggle_category_status(request, category_id):
    if not request.user.is_staff:
        return HttpResponseForbidden(
            'You are not authorized to perform this action.'
        )

    category = get_object_or_404(
        Category,
        id=category_id
    )

    category.is_active = not category.is_active
    category.save(update_fields=['is_active', 'updated_at'])

    if category.is_active:
        messages.success(
            request,
            f'"{category.name}" activated successfully.'
        )
    else:
        messages.warning(
            request,
            f'"{category.name}" deactivated successfully.'
        )

    return redirect('category_list')