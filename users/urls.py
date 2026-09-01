from django.urls import path
from users import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('', views.home, name='home'),
    path("signup/", views.signup, name='signup'),
    path('verify-signup-otp/<uuid:signup_id>/', views.verify_signup_otp,name='verify_signup_otp'),
    path('resend-signup-otp/<uuid:signup_id>/', views.resend_signup_otp,name='resend_signup_otp'),
    path("login/", views.login_view, name='login'),
    path("profile/", views.profile, name='profile'),
    path('profile/edit/', views.edit_profile, name='edit_profile'),
    path('profile/security/', views.security, name='security'),
    path("profile/security/change-email/", views.change_email,name="change_email"),
    path("profile/security/change-email/<uuid:change_email_id>/", views.verify_change_email, name="verify_change_email"),
    path("profile/security/change-email/<uuid:change_email_id>/resend/", views.resend_change_email_otp, name="resend_change_email_otp"),
    path("profile/security/change-password/", views.change_password, name="change_password"),
    path("profile/addresses/",views.addresses,name="addresses"),
    path("profile/addresses/", views.addresses, name="addresses"),
    path("profile/addresses/add/", views.add_address, name="add_address"),
    path("profile/addresses/<int:address_id>/edit/", views.edit_address, name="edit_address"),
    path("profile/addresses/<int:address_id>/default/", views.set_default_address, name="set_default_address"),
    path("profile/addresses/<int:address_id>/delete/", views.delete_address, name="delete_address"),
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
    path("logout/", views.logout_view, name="logout"),
]
