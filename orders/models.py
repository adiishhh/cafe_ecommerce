from django.db import models
from django.conf import settings
from product.models import Product

# Create your models here.

class Order(models.Model):

    class OrderType(models.TextChoices):
        PICKUP = "pickup", "Pickup"
        DELIVERY = "delivery", "Delivery"
        TABLE = "table", "Table"

    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        PREPARING = "preparing", "Preparing"
        READY = "ready", "Ready"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"

    order_no = models.CharField(
        max_length=20,
        unique=True,
    )

    tracking_no = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="orders",
    )

    order_type = models.CharField(
        max_length=20,
        choices=OrderType.choices,
    )

    table = models.ForeignKey(
        "tables.Table",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="orders",
    )

    address = models.ForeignKey(
        "users.Address",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="orders",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CONFIRMED,
    )

    instructions = models.TextField(
        blank=True,
    )

    subtotal = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    tax_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return self.order_no


class OrderItem(models.Model):

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="order_items",
    )

    quantity = models.PositiveIntegerField()

    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    instructions = models.TextField(
        blank=True,
    )

    subtotal = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    is_cancelled = models.BooleanField(
        default=False
    )
    
    cancellation_reason = models.TextField(
        blank=True
    )
    
    cancelled_at = models.DateTimeField(
        null=True,
        blank=True
    )

    def __str__(self):
        return f"{self.order.order_no} - {self.product.name}"