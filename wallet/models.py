from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator
from decimal import Decimal
import uuid

# Create your models here.

class Wallet(models.Model):

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="wallet",
    )

    balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00"))
        ],
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return f"Wallet - {self.user}"

class WalletTransaction(models.Model):

    class TransactionType(models.TextChoices):
        REFUND = "refund", "Refund"
        PAYMENT = "payment", "Payment"
        REFERRAL = "referral", "Referral"
        ADJUSTMENT = "adjustment", "Adjustment"

    class Direction(models.TextChoices):
        CREDIT = "credit", "Credit"
        DEBIT = "debit", "Debit"

    transaction_no = models.CharField(
        max_length=30,
        unique=True,
        editable=False,
    )

    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.PROTECT,
        related_name="transactions",
    )

    transaction_type = models.CharField(
        max_length=15,
        choices=TransactionType.choices,
    )

    direction = models.CharField(
        max_length=10,
        choices=Direction.choices,
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[
            MinValueValidator(Decimal("0.01"))
        ],
    )

    balance_after = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.PROTECT,
        related_name="wallet_transactions",
        null=True,
        blank=True,
    )

    payment = models.ForeignKey(
        "billing.Payment",
        on_delete=models.PROTECT,
        related_name="wallet_transactions",
        null=True,
        blank=True,
    )

    refund_request = models.OneToOneField(
        "billing.RefundRequest",
        on_delete=models.PROTECT,
        related_name="wallet_transaction",
        null=True,
        blank=True,
    )

    description = models.CharField(
        max_length=255,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    def save(self, *args, **kwargs):

        if not self.transaction_no:
            self.transaction_no = (
                f"WAL-{uuid.uuid4().hex[:12].upper()}"
            )

        super().save(*args, **kwargs)

    def __str__(self):
        return self.transaction_no