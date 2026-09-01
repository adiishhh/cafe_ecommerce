from django.shortcuts import render, redirect
from users.forms import SignupForm, SignupOTPForm, ProfileEditForm, ChangeEmailForm, ChangeEmailOTPForm
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import login, authenticate,get_user_model
from django.contrib.auth.decorators import login_required
import random
import uuid
from django.core.cache import cache
from django.core.mail import send_mail
from django.contrib.auth.hashers import make_password, check_password
import time
from django.contrib.auth import logout

# Create your views here.

User = get_user_model()

def home(request):
    return render(request, 'users/home.html')

def signup(request):
    if request.method == 'POST':
        form = SignupForm(request.POST)

        if form.is_valid():
            otp = str(random.randint(100000, 999999))
            signup_id =str(uuid.uuid4())
            signup_data = {
                'name': form.cleaned_data['name'],
                'email': form.cleaned_data['email'],
                'phone': form.cleaned_data['phone'],
                'password': make_password(form.cleaned_data['password1']),
                'otp': make_password(otp),
            }

            cache.set(
                f'signup_{signup_id}',
                signup_data,
                timeout=300
            )

            send_mail(
                subject='SmartCafe - Verify your email',
                message=f'Your SmartCafe verification OTP is: {otp}',
                from_email=None,
                recipient_list=[form.cleaned_data['email']],
            )

            cache.set(
                f'signup_resend_{signup_id}',
                time.time() + 60,
                timeout=60
            )
            return redirect('verify_signup_otp', signup_id=signup_id)

    else:
        form = SignupForm()

    return render(request, 'users/signup.html', {'form': form})

def verify_signup_otp(request, signup_id):

    signup_data = cache.get(f'signup_{signup_id}')

    if not signup_data:
        return redirect('signup')

    if request.method == 'POST':
        form = SignupOTPForm(request.POST)

        if form.is_valid():
            otp = form.cleaned_data['otp']

            if check_password(otp, signup_data['otp']):

                User.objects.create(
                    name=signup_data['name'],
                    email=signup_data['email'],
                    phone=signup_data['phone'],
                    password=signup_data['password'],
                )

                cache.delete(f'signup_{signup_id}')

                return redirect('login')
            else:
                form.add_error('otp', 'Invalid OTP. Please try again.')

    else:
        form = SignupOTPForm()

    cooldown_until = cache.get(f'signup_resend_{signup_id}')
    if cooldown_until:
        resend_available_in = max(0,int(cooldown_until - time.time()))
    else:
        resend_available_in = 0

    return render(request,'users/verify_signup_otp.html',
    {
        'form': form,
        'signup_id': signup_id,
        'resend_available_in': resend_available_in,
    })

def resend_signup_otp(request, signup_id):

    signup_data = cache.get(f'signup_{signup_id}')

    if not signup_data:
        return redirect('signup')

    cooldown_until = cache.get(f'signup_resend_{signup_id}')

    if cooldown_until:
        return redirect(
            'verify_signup_otp',
            signup_id=signup_id
        )

    otp = str(random.randint(100000, 999999))

    signup_data['otp'] = make_password(otp)

    cache.set(
        f'signup_{signup_id}',
        signup_data,
        timeout=300
    )

    send_mail(
        subject='SmartCafe - New verification OTP',
        message=f'Your new SmartCafe verification OTP is: {otp}',
        from_email=None,
        recipient_list=[signup_data['email']],
    )

    cache.set(
        f'signup_resend_{signup_id}',
        time.time() + 60,
        timeout=60
    )

    return redirect(
        'verify_signup_otp',
        signup_id=signup_id
    )

def login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)

        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect('home')

    else:
        form = AuthenticationForm()

    return render(request, 'users/login.html', {'form': form})

@login_required
def profile(request):
    default_address = request.user.addresses.filter(is_default=True).first()
    return render(request, 'users/profile.html', {'default_address': default_address})

@login_required
def edit_profile(request):
    if request.method == 'POST':
        form = ProfileEditForm(request.POST, request.FILES, instance=request.user)

        if form.is_valid():
            form.save()
            return redirect('profile')

    else:
        form = ProfileEditForm(instance=request.user)

    return render(request, 'users/edit_profile.html', {'form': form})

@login_required
def security(request):
    return render(request, 'users/security.html')

@login_required
def change_email(request):
    if request.method == 'POST':
        form = ChangeEmailForm(request.POST, user=request.user)

        if form.is_valid():
            new_email = form.cleaned_data['new_email']
            otp = str(random.randint(100000, 999999))
            change_email_id = str(uuid.uuid4())
            change_email_data =  {
                "user_id": request.user.id,
                "new_email": new_email,
                "otp": make_password(otp),
            }

            cache.set(
                f"change_email_{change_email_id}",
                change_email_data,
                timeout=300
            )

            send_mail(
                subject="SmartCafe - Verify your new email",
                message=(
                    f"Your SmartCafe email change OTP is: {otp}"
                ),
                from_email=None,
                recipient_list=[new_email],
            )

            cache.set(
                f"change_email_resend_{change_email_id}",
                time.time() + 60,
                timeout=60
            )

            return redirect('verify_change_email', change_email_id=change_email_id)

    else:
        form = ChangeEmailForm(
            user=request.user
        )

    return render(request, 'users/change_email.html', {'form': form})

@login_required
def verify_change_email(request, change_email_id):
    change_email_data = cache.get(f"change_email_{change_email_id}")

    if not change_email_data:
        return redirect('change_email')

    if change_email_data['user_id'] != request.user.id:
        return redirect('security')

    if request.method == 'POST':
        form = ChangeEmailOTPForm(request.POST)

        if form.is_valid():
            otp = form.cleaned_data['otp']

            if check_password(otp, change_email_data['otp']):
                request.user.email = change_email_data['new_email']
                request.user.save(update_fields=['email'])

                cache.delete(f"change_email_{change_email_id}")

                cache.delete(f"change_email_resend_{change_email_id}")

                return redirect('security')
            
            else:
                form.add_error("otp", "Invalid OTP")
    else:
         form = ChangeEmailOTPForm()

    cooldown_until = cache.get(
        f"change_email_resend_{change_email_id}"
    )

    if cooldown_until:
        resend_available_in = max(
            0,
            int(cooldown_until - time.time())
        )
    else:
        resend_available_in = 0

    return render(
        request,
        "users/verify_change_email.html",
        {
            "form": form,
            "change_email_id": change_email_id,
            "new_email": change_email_data["new_email"],
            "resend_available_in": resend_available_in,
        }
    )

@login_required
def  resend_change_email_otp(request, change_email_id):
    change_email_data = cache.get(
        f"change_email_{change_email_id}"
    )

    if not change_email_data:
        return redirect("change_email")

    if change_email_data["user_id"] != request.user.id:
        return redirect("security")

    cooldown_until = cache.get(
        f"change_email_resend_{change_email_id}"
    )

    if cooldown_until:
        return redirect(
            "verify_change_email",
            change_email_id=change_email_id
        )

    otp = str(random.randint(100000, 999999))

    change_email_data["otp"] = make_password(otp)

    cache.set(
        f"change_email_{change_email_id}",
        change_email_data,
        timeout=300
    )

    send_mail(
        subject="SmartCafe - New email verification OTP",
        message=(
            f"Your new SmartCafe email verification OTP is: {otp}"
        ),
        from_email=None,
        recipient_list=[change_email_data["new_email"]],
    )

    cache.set(
        f"change_email_resend_{change_email_id}",
        time.time() + 60,
        timeout=60
    )

    return redirect(
        "verify_change_email",
        change_email_id=change_email_id
    )

def logout_view(request):
    logout(request)
    return redirect('home')
