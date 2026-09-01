from django.urls import path
from users import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('', views.home, name='home'),
    path("signup/", views.signup, name='signup'),
    path("login/", views.login_view, name='login'),
    path("profile/", views.profile, name='profile'),
    path("logout/", views.logout_view, name="logout"),
    path('verify-signup-otp/<uuid:signup_id>/',views.verify_signup_otp,name='verify_signup_otp'),
    path('resend-signup-otp/<uuid:signup_id>/',views.resend_signup_otp,name='resend_signup_otp'),
    path(
        'forgot-password/', 
        auth_views.PasswordResetView.as_view(
            template_name='users/forgot_password.html',
            email_template_name='users/password_reset_email.html',
            subject_template_name='users/password_reset_subject.txt'
            ),
        name='password_reset'),
    path(
        "forgot-password/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="users/password_reset_done.html",
        ),
        name="password_reset_done",
    ),

    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="users/password_reset_confirm.html",
        ),
        name="password_reset_confirm",
    ),

    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="users/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),
]
