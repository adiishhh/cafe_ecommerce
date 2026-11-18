from django import forms

from .models import Table


class TableForm(forms.ModelForm):

    class Meta:

        model = Table

        fields = [
            "table_number",
            "capacity",
        ]

        widgets = {
            "table_number": forms.NumberInput(
                attrs={
                    "class": "form-input",
                    "placeholder": "Enter table number",
                    "min": 1,
                }
            ),
            "capacity": forms.NumberInput(
                attrs={
                    "class": "form-input",
                    "placeholder": "Enter seating capacity",
                    "min": 1,
                }
            ),
        }

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        self.fields["capacity"].required = False

    def clean_table_number(self):

        table_number = self.cleaned_data["table_number"]

        existing_table = Table.objects.filter(table_number=table_number)

        if self.instance.pk:
            existing_table = existing_table.exclude(pk=self.instance.pk)

        if existing_table.exists():
            raise forms.ValidationError("A table with this number already exists.")

        return table_number
