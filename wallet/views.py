from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from decimal import Decimal
from django.db import transaction

from wallet.models import Wallet, WalletTransaction
from billing.models import RefundRequest


# Create your views here.


User = get_user_model()


def get_customer_wallet(user):

    if not user.is_authenticated:

        raise PermissionDenied(
            "Authentication is required."
        )

    if user.is_staff or user.is_superuser:

        raise PermissionDenied(
            "Administrative users do not have a wallet."
        )

    wallet, created = Wallet.objects.get_or_create(
        user=user
    )

    return wallet


@transaction.atomic
def credit_wallet(
    user,
    amount,
    transaction_type,
    order=None,
    payment=None,
    refund_request=None,
    description="",
):

    amount = Decimal(
        str(amount)
    )

    if amount <= Decimal("0.00"):

        raise ValidationError(
            "Wallet credit amount must be greater than zero."
        )

    wallet = get_customer_wallet(user)

    wallet = (
        Wallet.objects
        .select_for_update()
        .get(
            pk=wallet.pk
        )
    )

    wallet.balance += amount

    wallet.save(
        update_fields=[
            "balance",
            "updated_at",
        ]
    )

    wallet_transaction = (
        WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type=transaction_type,
            direction=WalletTransaction.Direction.CREDIT,
            amount=amount,
            balance_after=wallet.balance,
            order=order,
            payment=payment,
            refund_request=refund_request,
            description=description,
        )
    )

    return (
        wallet,
        wallet_transaction,
    )


@transaction.atomic
def debit_wallet(
    user,
    amount,
    transaction_type,
    order=None,
    payment=None,
    refund_request=None,
    description="",
):

    amount = Decimal(
        str(amount)
    )

    if amount <= Decimal("0.00"):

        raise ValidationError(
            "Wallet debit amount must be greater than zero."
        )

    wallet = get_customer_wallet(user)

    wallet = (
        Wallet.objects
        .select_for_update()
        .get(
            pk=wallet.pk
        )
    )

    if wallet.balance < amount:

        raise ValidationError(
            "Insufficient wallet balance."
        )

    wallet.balance -= amount

    wallet.save(
        update_fields=[
            "balance",
            "updated_at",
        ]
    )

    wallet_transaction = (
        WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type=transaction_type,
            direction=WalletTransaction.Direction.DEBIT,
            amount=amount,
            balance_after=wallet.balance,
            order=order,
            payment=payment,
            refund_request=refund_request,
            description=description,
        )
    )

    return (
        wallet,
        wallet_transaction,
    )


@login_required(login_url="login")
def wallet_page(request):

    if request.user.is_staff or request.user.is_superuser:

        raise PermissionDenied(
            "Administrative users do not have a wallet."
        )

    wallet = get_customer_wallet(
        request.user
    )

    transactions = (
        wallet.transactions
        .select_related(
            "order",
            "payment",
            "refund_request",
        )
        .order_by(
            "-created_at",
            "-id",
        )
    )

    refund_requests = (
        RefundRequest.objects
        .filter(
            user=request.user,
        )
        .select_related(
            "order",
            "order_item",
            "order_item__product",
            "bill",
            "reviewed_by",
        )
        .order_by(
            "-created_at",
            "-id",
        )
    )

    return render(
        request,
        "users_panel/wallet.html",
        {
            "wallet": wallet,
            "transactions": transactions,
            "refund_requests": refund_requests,
        },
    )