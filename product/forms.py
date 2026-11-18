import re

from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone

from .models import Product, ProductImage


class ProductForm(forms.ModelForm):

    class Meta:
        model = Product

        fields = [
            "category",
            "name",
            "description",
            "base_price",
            "offer_percentage",
            "offer_valid_until",
            "is_active",
        ]

        widgets = {
            "category": forms.Select(
                attrs={
                    "class": "form-input",
                }
            ),
            "name": forms.TextInput(
                attrs={
                    "class": "form-input",
                    "placeholder": "Enter product name",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-input",
                    "placeholder": "Enter product description",
                    "rows": 4,
                }
            ),
            "base_price": forms.NumberInput(
                attrs={
                    "class": "form-input",
                    "placeholder": "Enter price",
                    "step": "0.01",
                    "min": "0.01",
                }
            ),
            "offer_percentage": forms.NumberInput(
                attrs={
                    "class": "form-input",
                    "placeholder": "Enter offer percentage",
                    "step": "0.01",
                    "min": "0",
                    "max": "100",
                }
            ),
            "offer_valid_until": forms.DateInput(
                attrs={
                    "class": "form-input",
                    "type": "date",
                }
            ),
            "is_active": forms.CheckboxInput(
                attrs={
                    "class": "form-checkbox",
                }
            ),
        }

    def clean_name(self):
        name = self.cleaned_data["name"].strip()

        if not name:
            raise forms.ValidationError("Product name is required.")

        if not re.search(r"[A-Za-z0-9]", name):
            raise forms.ValidationError(
                "Product name must contain at least one letter or number."
            )

        queryset = Product.objects.filter(name__iexact=name)

        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise forms.ValidationError("A product with this name already exists.")

        return name

    def clean_description(self):
        description = self.cleaned_data["description"].strip()

        if description and not re.search(r"[A-Za-z0-9]", description):
            raise forms.ValidationError(
                "Description must contain at least one letter or number."
            )

        return description

    def clean_price(self):
        price = self.cleaned_data["base_price"]

        if price <= 0:
            raise forms.ValidationError("Price must be greater than 0.")

        return price

    def clean(self):
        cleaned_data = super().clean()

        offer_percentage = cleaned_data.get("offer_percentage")

        offer_valid_until = cleaned_data.get("offer_valid_until")

        if offer_percentage is None:
            return cleaned_data

        if offer_percentage > 0:

            if not offer_valid_until:
                self.add_error(
                    "offer_valid_until",
                    "A validity date is required when an offer is applied.",
                )

            elif offer_valid_until < timezone.localdate():
                self.add_error(
                    "offer_valid_until",
                    "The offer validity date cannot be in the past.",
                )

        elif offer_valid_until and offer_valid_until < timezone.localdate():
            self.add_error(
                "offer_valid_until", "The validity date cannot be in the past."
            )

        return cleaned_data


class ProductImageForm(forms.ModelForm):

    class Meta:
        model = ProductImage
        fields = ["image"]

        widgets = {
            "image": forms.ClearableFileInput(
                attrs={
                    "class": "form-input",
                    "accept": "image/*",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["image"].required = False


ProductImageFormSet = inlineformset_factory(
    Product,
    ProductImage,
    form=ProductImageForm,
    extra=3,
    can_delete=True,
)
