from django.db import models

# Create your models here.

class Table(models.Model):
    table_number = models.PositiveIntegerField(unique=True)
    qr_token = models.CharField(max_length=100, unique=True)
    capacity = models.PositiveIntegerField(null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Table {self.table_number}"