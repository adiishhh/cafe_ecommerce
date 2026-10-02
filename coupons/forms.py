from django import forms
from django.utils import timezone

from .models import Coupon


class CouponForm(forms.ModelForm):

    class Meta:
        model = Coupon

        fields = [
            "code",
            "discount_type",
            "discount_value",
            "minimum_order_amount",
            "maximum_discount_amount",
            "usage_limit",
            "valid_from",
            "valid_until",
            "is_active",
        ]

        widgets = {
            "code": forms.TextInput(
                attrs={
                    "placeholder": "Enter coupon code",
                    "autocomplete": "off",
                }
            ),

            "discount_type": forms.Select(),

            "discount_value": forms.NumberInput(
                attrs={
                    "placeholder": "Enter discount value",
                    "step": "0.01",
                    "min": "0",
                }
            ),

            "minimum_order_amount": forms.NumberInput(
                attrs={
                    "placeholder": "Enter minimum order amount",
                    "step": "0.01",
                    "min": "0",
                }
            ),

            "maximum_discount_amount": forms.NumberInput(
                attrs={
                    "placeholder": "Enter maximum discount",
                    "step": "0.01",
                    "min": "0",
                }
            ),

            "usage_limit": forms.NumberInput(
                attrs={
                    "placeholder": "Enter maximum limit",
                    "min": "1",
                }
            ),

            "valid_from": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                },
                format="%Y-%m-%dT%H:%M",
            ),

            "valid_until": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                },
                format="%Y-%m-%dT%H:%M",
            ),

            "is_active": forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        self.fields["valid_from"].input_formats = [
            "%Y-%m-%dT%H:%M"
        ]

        self.fields["valid_until"].input_formats = [
            "%Y-%m-%dT%H:%M"
        ]

        if self.instance and self.instance.pk:

            if self.instance.valid_from:

                self.initial["valid_from"] = (
                    timezone.localtime(
                        self.instance.valid_from
                    ).strftime("%Y-%m-%dT%H:%M")
                )

            if self.instance.valid_until:

                self.initial["valid_until"] = (
                    timezone.localtime(
                        self.instance.valid_until
                    ).strftime("%Y-%m-%dT%H:%M")
                )

    def clean_code(self):

        code = self.cleaned_data["code"].strip().upper()

        if not code:
            raise forms.ValidationError(
                "Coupon code cannot be empty."
            )

        return code

    def clean_discount_value(self):

        value = self.cleaned_data["discount_value"]

        if value <= 0:
            raise forms.ValidationError(
                "Discount value must be greater than zero."
            )

        return value

    def clean_minimum_order_amount(self):

        value = self.cleaned_data["minimum_order_amount"]

        if value < 0:
            raise forms.ValidationError(
                "Minimum order amount cannot be negative."
            )

        return value

    def clean_maximum_discount_amount(self):

        value = self.cleaned_data["maximum_discount_amount"]

        if value is not None and value <= 0:
            raise forms.ValidationError(
                "Maximum discount must be greater than zero."
            )

        return value

    def clean_usage_limit(self):

        value = self.cleaned_data["usage_limit"]

        if value is not None and value <= 0:
            raise forms.ValidationError(
                "Usage limit must be greater than zero."
            )

        return value

    def clean(self):

        cleaned_data = super().clean()

        discount_type = cleaned_data.get("discount_type")
        discount_value = cleaned_data.get("discount_value")
        maximum_discount = cleaned_data.get(
            "maximum_discount_amount"
        )

        valid_from = cleaned_data.get("valid_from")
        valid_until = cleaned_data.get("valid_until")

        if (
            discount_type == Coupon.DiscountType.PERCENTAGE
            and discount_value is not None
            and discount_value > 100
        ):
            self.add_error(
                "discount_value",
                "Percentage discount cannot exceed 100%.",
            )

        if (
            discount_type == Coupon.DiscountType.FIXED
            and maximum_discount is not None
        ):
            self.add_error(
                "maximum_discount_amount",
                "Maximum discount is only applicable to percentage coupons.",
            )

        if (
            valid_from
            and valid_until
            and valid_from >= valid_until
        ):
            self.add_error(
                "valid_until",
                "Valid until must be later than valid from.",
            )

        return cleaned_data