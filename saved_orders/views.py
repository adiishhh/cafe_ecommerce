from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from .models import SavedOrder

# Create your views here.

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