import secrets
from django.db import models

def generate_qr_token():
    return secrets.token_urlsafe(32)


class Table(models.Model):

    table_number = models.PositiveIntegerField(unique=True)

    qr_token = models.CharField(
        max_length=100,
        unique=True,
        default=generate_qr_token
    )

    capacity = models.PositiveIntegerField(null=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Table {self.table_number}"