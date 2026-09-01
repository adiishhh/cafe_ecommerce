from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm, PasswordChangeForm
from django import forms


User = get_user_model()

class SignupForm(UserCreationForm):
     class Meta:
          model = User
          fields = ['name', 'email', 'phone']

class SignupOTPForm(forms.Form):
     otp = forms.CharField(max_length=6, min_length=6, widget=forms.TextInput(attrs={'placeholder': 'Enter 6-digit OTP'}))

class ProfileEditForm(forms.ModelForm):
     class Meta:
          model = User
          fields = ['name', 'phone', 'profile_image']
          widgets = {
               'name':forms.TextInput(attrs={'placeholder': 'Enter your name'}),
               'phone':forms.TextInput(attrs={'placeholder': 'Enter you phone number'}),
          }

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
