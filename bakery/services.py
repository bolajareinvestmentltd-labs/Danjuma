from decimal import Decimal, InvalidOperation
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core import signing
from django.core.signing import BadSignature, SignatureExpired
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (
    Order,
    OrderItem,
    OrderStatusHistory,
    Product,
    Subscription,
    SubscriptionPreparation,
)


ALLOWED_STATUS_TRANSITIONS = {
    Order.Status.PENDING: {
        Order.Status.PAID,
        Order.Status.PREPARATION_QUEUED,
        Order.Status.CANCELLED,
    },
    Order.Status.PREPARATION_QUEUED: {Order.Status.BAKING, Order.Status.CANCELLED},
    Order.Status.PAID: {Order.Status.BAKING, Order.Status.CANCELLED},
    Order.Status.BAKING: {Order.Status.DISPATCHED, Order.Status.CANCELLED},
    Order.Status.DISPATCHED: {Order.Status.DELIVERED},
    Order.Status.DELIVERED: set(),
    Order.Status.CANCELLED: set(),
}


def _delivery_fee():
    try:
        fee = Decimal(str(getattr(settings, "DELIVERY_SERVICE_FEE", "0.00")))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError("Delivery fee configuration is invalid.") from exc
    if not fee.is_finite() or fee < 0:
        raise ValidationError("Delivery fee configuration must be finite and non-negative.")
    return fee


@transaction.atomic
def create_order(*, user, cart, fulfillment_type, delivery_address="", scheduled_date=None,
                 scheduled_time_slot="", slicing_preference="Unsliced"):
    if fulfillment_type not in Order.FulfillmentType.values:
        raise ValidationError("Choose a valid fulfillment method.")
    if fulfillment_type == Order.FulfillmentType.DELIVERY and not delivery_address.strip():
        raise ValidationError("A delivery address is required.")
    if scheduled_date and scheduled_date < timezone.localdate():
        raise ValidationError("Choose a delivery date that is today or later.")
    if not isinstance(cart, dict) or not cart:
        raise ValidationError("Your basket is empty.")

    try:
        product_ids = sorted({int(product_id) for product_id in cart})
    except (TypeError, ValueError) as exc:
        raise ValidationError("Your basket contains an invalid product.") from exc
    products = list(
        Product.objects.select_for_update()
        .filter(pk__in=product_ids, is_active=True, branch__is_active=True)
        .select_related("branch")
        .order_by("pk")
    )
    if len(products) != len(product_ids):
        raise ValidationError("A product in your basket is no longer available.")
    branches = {product.branch_id for product in products}
    if len(branches) != 1:
        raise ValidationError("Please order from one branch at a time.")

    line_items = []
    subtotal = Decimal("0.00")
    for product in products:
        try:
            quantity = int(cart.get(str(product.pk), cart.get(product.pk)))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("Your basket contains an invalid quantity.") from exc
        if quantity < 1 or quantity > 99:
            raise ValidationError("Each item quantity must be between 1 and 99.")
        if product.stock_qty < quantity:
            raise ValidationError(f"Only {product.stock_qty} of {product.title} are available.")
        subtotal += product.price * quantity
        line_items.append((product, quantity))

    service_fee = _delivery_fee() if fulfillment_type == Order.FulfillmentType.DELIVERY else Decimal("0.00")
    order = Order.objects.create(
        user=user,
        branch=products[0].branch,
        fulfillment_type=fulfillment_type,
        total_amount=subtotal + service_fee,
        service_fee=service_fee,
        delivery_address=delivery_address.strip() if fulfillment_type == Order.FulfillmentType.DELIVERY else "",
        scheduled_date=scheduled_date,
        scheduled_time_slot=scheduled_time_slot.strip(),
        slicing_preference=slicing_preference.strip()[:40] or "Unsliced",
    )
    for product, quantity in line_items:
        product.stock_qty -= quantity
        product.save(update_fields=("stock_qty", "updated_at"))
        OrderItem.objects.create(
            order=order,
            product=product,
            title_snapshot=product.title,
            quantity=quantity,
            unit_price=product.price,
        )
    OrderStatusHistory.objects.create(order=order, new_status=order.status, changed_by=user)
    return order


@transaction.atomic
def transition_order(*, order, new_status, actor, note=""):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if new_status not in ALLOWED_STATUS_TRANSITIONS.get(order.status, set()):
        raise ValidationError("That order status transition is not allowed.")
    old_status = order.status
    order.status = new_status
    update_fields = ["status", "delivered_at", "inventory_released", "updated_at"]
    if new_status == Order.Status.PAID and order.fulfillment_type == Order.FulfillmentType.DELIVERY:
        order.qr_code_payload = signing.dumps(
            {"order_id": order.pk}, salt="bakery.dispatch.v1"
        )
        update_fields.append("qr_code_payload")
    if new_status == Order.Status.DELIVERED:
        order.delivered_at = timezone.now()
    if new_status == Order.Status.CANCELLED and not order.inventory_released:
        for item in order.items.select_related("product").order_by("product_id"):
            product = Product.objects.select_for_update().get(pk=item.product_id)
            product.stock_qty += item.quantity
            product.save(update_fields=("stock_qty", "updated_at"))
        order.inventory_released = True
    order.save(update_fields=update_fields)
    OrderStatusHistory.objects.create(
        order=order,
        old_status=old_status,
        new_status=new_status,
        changed_by=actor,
        note=note.strip()[:255],
    )
    return order


def verify_dispatch_token(*, token, dispatcher):
    if dispatcher.role != dispatcher.Role.DISPATCHER or not dispatcher.branch_id:
        raise ValidationError("A branch-assigned dispatcher must verify delivery.")
    try:
        data = signing.loads(
            token,
            salt="bakery.dispatch.v1",
            max_age=settings.QR_TOKEN_MAX_AGE,
        )
        order_id = data["order_id"]
    except (BadSignature, SignatureExpired, KeyError, TypeError) as exc:
        raise ValidationError("The dispatch token is invalid or expired.") from exc
    try:
        order_id = int(order_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError("The dispatch token is invalid or expired.") from exc

    try:
        order = Order.objects.get(pk=order_id)
    except Order.DoesNotExist as exc:
        raise ValidationError("The dispatch token does not match an order.") from exc
    if order.qr_code_payload != token:
        raise ValidationError("The dispatch token has been replaced.")
    if order.branch_id != dispatcher.branch_id:
        raise ValidationError("This order belongs to another branch.")
    if order.status != Order.Status.DISPATCHED:
        raise ValidationError("Only dispatched orders can be verified for delivery.")
    return transition_order(
        order=order,
        new_status=Order.Status.DELIVERED,
        actor=dispatcher,
        note="Delivery verified by branch dispatcher.",
    )


def _next_delivery_date(frequency, delivery_date):
    if frequency == Subscription.Frequency.DAILY:
        return delivery_date + timedelta(days=1)
    if frequency == Subscription.Frequency.WEEKLY:
        return delivery_date + timedelta(days=7)
    if frequency == Subscription.Frequency.BIWEEKLY:
        return delivery_date + timedelta(days=14)
    raise ValidationError("Subscription frequency is invalid.")


@transaction.atomic
def _create_subscription_preparation(subscription_id, today):
    subscription = Subscription.objects.select_for_update().get(pk=subscription_id)
    if not subscription.is_active or subscription.next_delivery_date > today:
        return None
    items = list(
        subscription.items.select_related("product", "product__branch").order_by("product_id")
    )
    if not items:
        raise ValidationError("Subscription has no products.")
    if any(
        item.product.branch_id != subscription.branch_id or not item.product.is_active
        for item in items
    ):
        raise ValidationError("A subscribed product is no longer available at its branch.")
    cart = {str(item.product_id): item.quantity for item in items}
    delivery_date = today
    order = create_order(
        user=subscription.user,
        cart=cart,
        fulfillment_type=(
            Order.FulfillmentType.DELIVERY
            if subscription.delivery_address
            else Order.FulfillmentType.PICKUP
        ),
        delivery_address=subscription.delivery_address,
        scheduled_date=delivery_date,
        scheduled_time_slot=subscription.preferred_time.strftime("%H:%M"),
        slicing_preference=subscription.slicing_preference,
    )
    order = transition_order(
        order=order,
        new_status=Order.Status.PREPARATION_QUEUED,
        actor=None,
        note="Subscription preparation; recurring billing is not processed.",
    )
    try:
        SubscriptionPreparation.objects.create(
            subscription=subscription, order=order, delivery_date=delivery_date
        )
    except IntegrityError:
        raise ValidationError("A preparation order already exists for this subscription date.")
    subscription.next_delivery_date = _next_delivery_date(
        subscription.frequency, delivery_date
    )
    subscription.save(update_fields=("next_delivery_date", "updated_at"))
    return order


def process_due_subscriptions(*, today=None):
    today = today or timezone.localdate()
    due_ids = list(
        Subscription.objects.filter(is_active=True, next_delivery_date__lte=today)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    created = []
    failed = []
    for subscription_id in due_ids:
        try:
            order = _create_subscription_preparation(subscription_id, today)
        except (ValidationError, IntegrityError) as exc:
            failed.append({"subscription_id": subscription_id, "reason": " ".join(exc.messages)
                           if isinstance(exc, ValidationError) else "Could not create preparation."})
        else:
            if order is not None:
                created.append(order)
    return {"created": created, "failed": failed}
