from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from decimal import Decimal
from wallet.models import Wallet, WalletTransaction, ReferralCode, ReferralUsage
from billing.models import RefundRequest
from django.contrib import messages
from django.db import transaction, IntegrityError
from django.http import JsonResponse
from django.utils import timezone

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

    # ---------------------------------------------------------
    # REFERRAL DATA
    # ---------------------------------------------------------

    referral_code = (
        ReferralCode.objects
        .filter(
            user=request.user,
        )
        .first()
    )

    pending_referral = (
        ReferralUsage.objects
        .filter(
            user=request.user,
            status=ReferralUsage.Status.PENDING,
        )
        .select_related(
            "code",
            "code__user",
        )
        .first()
    )

    referral_usages = (
        ReferralUsage.objects
        .filter(
            user=request.user,
        )
        .select_related(
            "code",
            "qualifying_order",
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

            "referral_code": referral_code,
            "pending_referral": pending_referral,
            "referral_usages": referral_usages,
        },
    )

@login_required(login_url="login")
def generate_referral_code(request):

    if request.method != "POST":

        return JsonResponse(
            {
                "success": False,
                "message": "Invalid request method.",
            },
            status=405,
        )

    if request.user.is_staff or request.user.is_superuser:

        return JsonResponse(
            {
                "success": False,
                "message": (
                    "You are not allowed to use "
                    "the referral program."
                ),
            },
            status=403,
        )

    try:

        with transaction.atomic():

            referral_code, created = (
                ReferralCode.objects.get_or_create(
                    user=request.user,
                )
            )

    except IntegrityError:

        return JsonResponse(
            {
                "success": False,
                "message": (
                    "Unable to generate your referral code. "
                    "Please try again."
                ),
            },
            status=409,
        )

    return JsonResponse(
        {
            "success": True,
            "created": created,
            "code": referral_code.code,
            "message": (
                "Your referral code has been generated successfully."
                if created
                else
                "You already have a referral code."
            ),
        }
    )

@login_required(login_url="login")
@transaction.atomic
def apply_referral_code(request):

    if request.user.is_staff or request.user.is_superuser:

        raise PermissionDenied(
            "Administrative users do not have access to customer referrals."
        )

    if request.method != "POST":

        return redirect("wallet")

    code_value = (
        request.POST
        .get("referral_code", "")
        .strip()
        .upper()
    )

    if not code_value:

        messages.error(
            request,
            "Please enter a referral code.",
        )

        return redirect("wallet")

    try:

        referral_code = (
            ReferralCode.objects
            .select_related("user")
            .get(code=code_value)
        )

    except ReferralCode.DoesNotExist:

        messages.error(
            request,
            "That referral code does not exist.",
        )

        return redirect("wallet")

    # Prevent self-referral.

    if referral_code.user_id == request.user.id:

        messages.error(
            request,
            "You cannot use your own referral code.",
        )

        return redirect("wallet")

    # The same customer cannot use the same person's
    # referral code more than once.

    if ReferralUsage.objects.filter(
        code=referral_code,
        user=request.user,
    ).exists():

        messages.error(
            request,
            "You have already used this referral code.",
        )

        return redirect("wallet")

    # Prevent multiple pending referral codes
    # from being stacked at the same time.

    if ReferralUsage.objects.filter(
        user=request.user,
        status=ReferralUsage.Status.PENDING,
    ).exists():

        messages.error(
            request,
            "You already have a pending referral. Complete that referral before using another code.",
        )

        return redirect("wallet")

    try:

        ReferralUsage.objects.create(
            code=referral_code,
            user=request.user,
        )

    except IntegrityError:

        messages.error(
            request,
            "This referral code could not be applied. Please try again.",
        )

        return redirect("wallet")

    messages.success(
        request,
        "Referral code applied successfully. You will receive 5% cashback when your qualifying order is completed.",
    )

    return redirect("wallet")

def reward_referral_for_order(order):
    """
    Reward the pending referral associated with this customer's
    first eligible completed order.

    Customer receives 5%.
    Referral-code owner receives 10%.

    This function must be called while the order is being
    transitioned to DELIVERED.
    """

    if order.status != order.Status.DELIVERED:
        return None

    if order.user_id is None:
        return None

    referral_usage = (
        ReferralUsage.objects
        .select_for_update()
        .select_related(
            "code",
            "code__user",
        )
        .filter(
            user_id=order.user_id,
            status=ReferralUsage.Status.PENDING,
        )
        .first()
    )

    if referral_usage is None:
        return None

    # ---------------------------------------------------------
    # IDEMPOTENCY
    # ---------------------------------------------------------

    # A referral can only be rewarded once.
    if referral_usage.qualifying_order_id is not None:
        return None

    # The qualifying order must have been created
    # after the referral code was applied.
    if order.created_at <= referral_usage.created_at:
        return None

    # ---------------------------------------------------------
    # FINAL ELIGIBLE ORDER AMOUNT
    # ---------------------------------------------------------

    eligible_amount = (
        Decimal(str(order.total_amount))
        .quantize(Decimal("0.01"))
    )

    if eligible_amount <= Decimal("0.00"):
        return None

    # ---------------------------------------------------------
    # CASHBACK RATES
    # ---------------------------------------------------------

    customer_rate = Decimal("0.05")
    owner_rate = Decimal("0.10")

    customer_cashback = (
        eligible_amount * customer_rate
    ).quantize(
        Decimal("0.01")
    )

    owner_cashback = (
        eligible_amount * owner_rate
    ).quantize(
        Decimal("0.01")
    )

    if customer_cashback <= Decimal("0.00"):
        return None

    if owner_cashback <= Decimal("0.00"):
        return None

    # ---------------------------------------------------------
    # CUSTOMER CASHBACK
    # ---------------------------------------------------------

    credit_wallet(
        user=order.user,
        amount=customer_cashback,
        transaction_type=WalletTransaction.TransactionType.REFERRAL,
        order=order,
        description=(
            f"5% referral cashback for order "
            f"{order.order_no}."
        ),
    )

    # ---------------------------------------------------------
    # REFERRAL OWNER CASHBACK
    # ---------------------------------------------------------

    credit_wallet(
        user=referral_usage.code.user,
        amount=owner_cashback,
        transaction_type=WalletTransaction.TransactionType.REFERRAL,
        order=order,
        description=(
            f"10% referral reward for referring "
            f"customer who completed order "
            f"{order.order_no}."
        ),
    )

    # ---------------------------------------------------------
    # FINALIZE REFERRAL USAGE
    # ---------------------------------------------------------

    referral_usage.status = (
        ReferralUsage.Status.REWARDED
    )

    referral_usage.qualifying_order = order

    referral_usage.eligible_amount = (
        eligible_amount
    )

    referral_usage.customer_cashback = (
        customer_cashback
    )

    referral_usage.owner_cashback = (
        owner_cashback
    )

    referral_usage.rewarded_at = timezone.now()

    referral_usage.save(
        update_fields=[
            "status",
            "qualifying_order",
            "eligible_amount",
            "customer_cashback",
            "owner_cashback",
            "rewarded_at",
        ]
    )

    return referral_usage