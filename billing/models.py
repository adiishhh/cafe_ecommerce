from django.db import models
from django.conf import settings
import uuid
from django.utils import timezone

# Create your models here.

class Bill(models.Model):

    class PaymentMethod(models.TextChoices):
        ONLINE = "online", "Online"
        COD = "cod", "Cash on Delivery"

    class TransactionMethod(models.TextChoices):
        CASH = "cash", "Cash"
        UPI = "upi", "UPI"
        CARD = "card", "Card"
        WALLET = "wallet", "Wallet"

    class Status(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PAID = "paid", "Paid"

    bill_no = models.CharField(
        max_length=30,
        unique=True,
        editable=False,
    )

    subtotal = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    tax_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    payment_method = models.CharField(
        max_length=10,
        choices=PaymentMethod.choices,
    )

    transaction_method = models.CharField(
        max_length=10,
        choices=TransactionMethod.choices,
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.UNPAID,
    )

    issued_at = models.DateTimeField(
        default=timezone.now,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def save(self, *args, **kwargs):
        if not self.bill_no:
            self.bill_no = (
                f"BILL-{uuid.uuid4().hex[:12].upper()}"
            )

        super().save(*args, **kwargs)

    def __str__(self):
        return self.bill_no

class BillOrder(models.Model):

    class PaymentMethod(models.TextChoices):
        ONLINE = "online", "Online"
        COD = "cod", "Cash on Delivery"

    order = models.OneToOneField(
        "orders.Order",
        on_delete=models.PROTECT,
        related_name="bill_order",
    )

    bill = models.ForeignKey(
        Bill,
        on_delete=models.PROTECT,
        related_name="bill_orders",
        null=True,
        blank=True,
    )

    total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    payment_method = models.CharField(
        max_length=10,
        choices=PaymentMethod.choices,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    def __str__(self):
        return f"BillOrder - {self.order.order_no}"

class RefundRequest(models.Model):

    class RefundType(models.TextChoices):
        ORDER = "order", "Full Order"
        ITEM = "item", "Individual Item"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        COMPLETED = "completed", "Completed"

    request_no = models.CharField(
        max_length=30,
        unique=True,
        editable=False,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="refund_requests",
    )

    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.PROTECT,
        related_name="refund_requests",
    )

    order_item = models.ForeignKey(
        "orders.OrderItem",
        on_delete=models.PROTECT,
        related_name="refund_requests",
        null=True,
        blank=True,
    )

    bill = models.ForeignKey(
        Bill,
        on_delete=models.PROTECT,
        related_name="refund_requests",
    )

    refund_type = models.CharField(
        max_length=10,
        choices=RefundType.choices,
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    reason = models.TextField()

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
    )

    admin_note = models.TextField(
        blank=True,
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewed_refund_requests",
        null=True,
        blank=True,
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def save(self, *args, **kwargs):

        if not self.request_no:
            self.request_no = (
                f"REF-{uuid.uuid4().hex[:12].upper()}"
            )

        super().save(*args, **kwargs)

    def __str__(self):
        return self.request_no

class Payment(models.Model):

    class TransactionMethod(models.TextChoices):
        CASH = "cash", "Cash"
        UPI = "upi", "UPI"
        CARD = "card", "Card"
        WALLET = "wallet", "Wallet"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESSFUL = "successful", "Successful"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    bill = models.ForeignKey(
        Bill,
        on_delete=models.PROTECT,
        related_name="payments",
    )

    transaction_method = models.CharField(
        max_length=10,
        choices=TransactionMethod.choices,
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    payment_reference = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.PENDING,
    )

    gateway = models.CharField(
        max_length=30,
        null=True,
        blank=True,
    )

    gateway_order_id = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
    )

    gateway_payment_id = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
    )

    gateway_event_id = models.CharField(
        max_length=150,
        unique=True,
        null=True,
        blank=True,
    )

    paid_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    refunded_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    refund_request = models.OneToOneField(
        "billing.RefundRequest",
        on_delete=models.PROTECT,
        related_name="refund_payment",
        null=True,
        blank=True,
    )

    refund_of = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="refund_payments",
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    def __str__(self):
        return (
            f"{self.get_transaction_method_display()} - "
            f"{self.bill.bill_no} - "
            f"{self.get_status_display()}"
        )