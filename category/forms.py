import re
from django import forms
from .models import Category


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'description']

        widgets = {
            'name': forms.TextInput(
                attrs={
                    'placeholder': 'Enter category name',
                }
            ),
            'description': forms.Textarea(
                attrs={
                    'placeholder': 'Enter category description',
                    'rows': 4,
                }
            ),
        }

    def clean_name(self):
        name = self.cleaned_data['name'].strip()

        if not name:
            raise forms.ValidationError(
                'Category name is required.'
            )

        if not re.search(r'[A-Za-z0-9]', name):
            raise forms.ValidationError(
                'Category name must contain at least one letter or number.'
            )

        queryset = Category.objects.filter(
            name__iexact=name
        )

        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise forms.ValidationError(
                'A category with this name already exists.'
            )

        return name

    def clean_description(self):
        description = self.cleaned_data['description'].strip()

        if description and not re.search(
            r'[A-Za-z0-9]',
            description
        ):
            raise forms.ValidationError(
                'Description must contain at least one letter or number.'
            )

        return description