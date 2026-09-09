import re
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django import forms
from users.models import Address


User = get_user_model()

class SignupForm(UserCreationForm):
    class Meta:
        model = User
        fields = ['name', 'email', 'phone']

    def clean_name(self):
        name = self.cleaned_data['name'].strip()

        if not re.fullmatch(r"[A-Za-z][A-Za-z\s.'-]*", name):
            raise forms.ValidationError(
                "Name can contain only letters, spaces, hyphens, apostrophes and periods."
            )

        return name

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()

        if not re.fullmatch(r"\d{7,15}", phone):
            raise forms.ValidationError(
                "Enter a valid phone number."
            )

        return phone

class SignupOTPForm(forms.Form):
    otp = forms.CharField(max_length=6, min_length=6, widget=forms.TextInput(attrs={'placeholder': 'Enter 6-digit OTP'}))

class ProfileEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['name', 'phone', 'profile_image']
        widgets = {
            'name': forms.TextInput(
                attrs={'placeholder': 'Enter your name'}
            ),
            'phone': forms.TextInput(
                attrs={'placeholder': 'Enter your phone number'}
            ),
        }

    def clean_name(self):
        name = self.cleaned_data['name'].strip()

        if not re.fullmatch(r"[A-Za-z][A-Za-z\s.'-]*", name):
            raise forms.ValidationError(
                "Name can contain only letters, spaces, hyphens, apostrophes and periods."
            )

        return name

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()

        if not re.fullmatch(r"\d{7,15}", phone):
            raise forms.ValidationError(
                "Enter a valid phone number."
            )

        return phone

class ChangeEmailForm(forms.Form):
    new_email = forms.EmailField(
         label = 'New Email',
         widget = forms.EmailInput(attrs={"placeholder": "Enter new email address"})
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_new_email(self):
        new_email = self.cleaned_data['new_email']

        if User.objects.filter(email=new_email).exclude(pk=self.user.pk).exists():             
            raise forms.ValidationError("This email address is already in use.")
        
        if new_email == self.user.email:
            raise forms.ValidationError("Please enter a different email address.")
        
        return new_email

class ChangeEmailOTPForm(forms.Form):
    otp = forms.CharField(max_length=6, min_length=6, widget=forms.TextInput(attrs={'placeholder': 'Enter 6-digit OTP'}))

class AddressForm(forms.ModelForm):
    class Meta:
        model = Address

        fields = [
            'name',
            'contact_number',
            'flat_house',
            'area_street',
            'city',
            'state',
            'pincode',
        ]

        labels = {
            'flat_house': 'Current residence',
            'area_street': 'Area / Street',
        }

        widgets = {
            'name': forms.TextInput(
                attrs={'placeholder': 'Recipient name'}
            ),
            'contact_number': forms.TextInput(
                attrs={'placeholder': 'Contact number'}
            ),
            'flat_house': forms.TextInput(
                attrs={'placeholder': 'Flat / House / Building'}
            ),
            'area_street': forms.TextInput(
                attrs={'placeholder': 'Area / Street / Locality'}
            ),
            'city': forms.TextInput(
                attrs={'placeholder': 'City'}
            ),
            'state': forms.TextInput(
                attrs={'placeholder': 'State'}
            ),
            'pincode': forms.TextInput(
                attrs={'placeholder': 'Pincode'}
            ),
        }

    def clean_name(self):
        name = self.cleaned_data['name'].strip()

        if not re.fullmatch(r"[A-Za-z][A-Za-z\s.'-]*", name):
            raise forms.ValidationError(
                "Enter a valid recipient name."
            )

        return name

    def clean_contact_number(self):
        contact_number = self.cleaned_data['contact_number'].strip()

        if not re.fullmatch(r"\d{7,15}", contact_number):
            raise forms.ValidationError(
                "Enter a valid contact number."
            )

        return contact_number

    def clean_flat_house(self):
        flat_house = self.cleaned_data['flat_house'].strip()
    
        if not re.search(r"[A-Za-z0-9]", flat_house):
            raise forms.ValidationError(
                "Enter valid flat, house or building details."
            )
    
        return flat_house

    def clean_area_street(self):
        area_street = self.cleaned_data['area_street'].strip()

        if not re.search(r"[A-Za-z0-9]", area_street):
            raise forms.ValidationError(
                "Enter a valid area or street."
            )

        return area_street  

    def clean_city(self):
        city = self.cleaned_data['city'].strip()

        if not re.fullmatch(r"[A-Za-z][A-Za-z\s.'-]*", city):
            raise forms.ValidationError(
                "Enter a valid city."
            )

        return city

    def clean_state(self):
        state = self.cleaned_data['state'].strip()

        if not re.fullmatch(r"[A-Za-z][A-Za-z\s.'-]*", state):
            raise forms.ValidationError(
                "Enter a valid state."
            )

        return state

    def clean_pincode(self):
        pincode = self.cleaned_data['pincode'].strip()

        if not re.fullmatch(r"\d{3,10}", pincode):
            raise forms.ValidationError(
                "Enter a valid pincode."
            )

        return pincode
