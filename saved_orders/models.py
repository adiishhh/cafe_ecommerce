from django.db import models
from django.conf import settings
from product.models import Product

# Create your models here.


class SavedOrder(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_orders",
    )
    name = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def total_amount(self):
        return sum(item.item_total for item in self.items.all())

    def __str__(self):
        return self.name


class SavedOrderItem(models.Model):
    saved_order = models.ForeignKey(
        SavedOrder,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="saved_order_items",
    )
    quantity = models.PositiveIntegerField()
    instructions = models.TextField(blank=True)

    @property
    def item_total(self):
        return self.product.price * self.quantity

    def __str__(self):
        return f"{self.saved_order.name} - {self.product.name}"