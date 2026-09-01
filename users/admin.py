from django.contrib import admin
from users.models import Address, User

# Register your models here.

admin.site.register(User)
admin.site.register(Address)