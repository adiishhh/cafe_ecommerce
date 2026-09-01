from dataclasses import fields

from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django import forms
from django.forms import widgets

import users

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