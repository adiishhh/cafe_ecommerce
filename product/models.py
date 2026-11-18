from django.db import models
from category.models import Category
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal, ROUND_HALF_UP
from django.utils import timezone

# Create your models here.


class Product(models.Model):

    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="products"
    )

    name = models.CharField(max_length=150)

    description = models.TextField()

    base_price = models.DecimalField(max_digits=10, decimal_places=2)

    offer_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[
            MinValueValidator(0),
            MaxValueValidator(100),
        ],
    )

    offer_valid_until = models.DateField(
        null=True,
        blank=True,
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    @property
    def has_active_offer(self):
        return (
            self.offer_percentage > Decimal("0")
            and self.offer_valid_until is not None
            and self.offer_valid_until >= timezone.localdate()
        )

    @property
    def discounted_price(self):
        discount = self.base_price * self.offer_percentage / Decimal("100")

        return (self.base_price - discount).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    @property
    def price(self):
        if self.has_active_offer:
            return self.discounted_price

        return self.base_price

    def __str__(self):
        return self.name


class ProductImage(models.Model):

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="images"
    )

    image = models.ImageField(upload_to="product_images/")

    created_at = models.DateTimeField(auto_now_add=True)


class ReviewRating(models.Model):

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="reviews",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="product_reviews",
    )

    rating = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(1),
            MaxValueValidator(5),
        ]
    )

    review = models.TextField(
        max_length=2000,
    )

    admin_reply = models.TextField(
        max_length=2000,
        blank=True,
    )

    replied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="product_review_replies",
    )

    replied_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:

        constraints = [
            models.UniqueConstraint(
                fields=["product", "user"],
                name="unique_user_review_per_product",
            ),
        ]

        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.user} - {self.product} " f"({self.rating}/5)"
