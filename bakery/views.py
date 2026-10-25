from decimal import Decimal
import secrets

from django.conf import settings
from django.db import DatabaseError, connection
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .forms import CheckoutForm, CustomerAddressForm, RegistrationForm
from .models import Branch, CustomerAddress, Order, Product, User
from .services import (
    create_order,
    process_due_subscriptions,
    transition_order,
    verify_dispatch_token,
)


@require_GET
def storefront(request):
    products = Product.objects.filter(is_active=True, branch__is_active=True).select_related("branch")
    category = request.GET.get("category", "").strip().upper()
    if category in Product.Category.values:
        products = products.filter(category=category)
    branches = Branch.objects.filter(is_active=True)
    return render(
        request,
        "bakery/storefront.html",
        {
            "products": products,
            "branches": branches,
            "category_choices": Product.Category.choices,
            "selected_category": category,
        },
    )


@require_GET
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "unavailable", "database": "error"}, status=503)
    return JsonResponse({"status": "ok", "database": "ok"})


def register(request):
    if request.user.is_authenticated:
        return redirect("bakery:storefront")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("bakery:storefront")
    return render(request, "bakery/register.html", {"form": form})


@login_required
def address_book(request):
    addresses = CustomerAddress.objects.filter(user=request.user)
    form = CustomerAddressForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            address = form.save(commit=False)
            address.user = request.user
            if address.is_default or not CustomerAddress.objects.filter(user=request.user).exists():
                CustomerAddress.objects.filter(user=request.user).update(is_default=False)
                address.is_default = True
            address.save()
        messages.success(request, "Address saved.")
        return redirect("bakery:address_book")
    return render(
        request,
        "bakery/address_book.html",
        {"addresses": addresses, "form": form},
    )


@login_required
@require_POST
def delete_address(request, address_id):
    address = get_object_or_404(CustomerAddress, pk=address_id, user=request.user)
    was_default = address.is_default
    with transaction.atomic():
        User.objects.select_for_update().get(pk=request.user.pk)
        address.delete()
        if was_default:
            replacement = (
                CustomerAddress.objects.filter(user=request.user).order_by("created_at", "pk").first()
            )
            if replacement:
                replacement.is_default = True
                replacement.save(update_fields=("is_default",))
    messages.success(request, "Address removed.")
    return redirect("bakery:address_book")


@require_POST
def add_to_cart(request, product_id):
    product = get_object_or_404(Product, pk=product_id, is_active=True, branch__is_active=True)
    try:
        quantity = int(request.POST.get("quantity", "1"))
    except (TypeError, ValueError):
        messages.error(request, "Enter a valid quantity.")
        return redirect("bakery:storefront")
    if not 1 <= quantity <= 99:
        messages.error(request, "Quantity must be between 1 and 99.")
        return redirect("bakery:storefront")

    cart = request.session.get("cart", {})
    if cart and str(product_id) not in cart:
        existing_branches = set(
            Product.objects.filter(pk__in=cart.keys()).values_list("branch_id", flat=True)
        )
        if existing_branches and existing_branches != {product.branch_id}:
            messages.error(request, "Your basket can contain items from one branch at a time.")
            return redirect("bakery:storefront")
    cart[str(product_id)] = min(int(cart.get(str(product_id), 0)) + quantity, 99)
    request.session["cart"] = cart
    request.session.modified = True
    messages.success(request, f"Added {product.title} to your basket.")
    return redirect("bakery:storefront")


@require_POST
def update_cart(request, product_id):
    cart = request.session.get("cart", {})
    if not isinstance(cart, dict):
        cart = {}
    key = str(product_id)
    if key not in cart:
        return redirect("bakery:checkout")
    try:
        quantity = int(request.POST.get("quantity", "0"))
    except (TypeError, ValueError):
        messages.error(request, "Enter a valid quantity.")
        return redirect("bakery:checkout")
    if quantity < 0 or quantity > 99:
        messages.error(request, "Quantity must be between 0 and 99.")
        return redirect("bakery:checkout")
    if quantity == 0:
        del cart[key]
    else:
        cart[key] = quantity
    request.session["cart"] = cart
    request.session.modified = True
    return redirect("bakery:checkout")


def _cart_products(request):
    cart = request.session.get("cart", {})
    if not isinstance(cart, dict):
        request.session.pop("cart", None)
        return []
    products = Product.objects.filter(
        pk__in=cart.keys(), is_active=True, branch__is_active=True
    ).select_related("branch")
    return [(product, cart.get(str(product.pk), 0)) for product in products]


@login_required
def checkout(request):
    cart_items = _cart_products(request)
    if request.method == "POST":
        form = CheckoutForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                order = create_order(
                    user=request.user,
                    cart=request.session.get("cart", {}),
                    **form.cleaned_data,
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                request.session["cart"] = {}
                messages.info(
                    request,
                    "Your order was created and is awaiting payment confirmation. No payment has been taken.",
                )
                return redirect("bakery:order_detail", order_id=order.pk)
    else:
        form = CheckoutForm(user=request.user)
    subtotal = Decimal("0.00")
    for product, quantity in cart_items:
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            continue
        if 1 <= quantity <= 99:
            subtotal += product.price * quantity
    return render(
        request,
        "bakery/checkout.html",
        {
            "form": form,
            "cart_items": cart_items,
            "subtotal": subtotal,
            "delivery_fee": settings.DELIVERY_SERVICE_FEE,
            "estimated_delivery_total": subtotal + settings.DELIVERY_SERVICE_FEE,
        },
    )


@login_required
def order_history(request):
    orders = Order.objects.filter(user=request.user).select_related("branch")
    return render(request, "bakery/order_history.html", {"orders": orders})


@login_required
@require_POST
def reorder(request, order_id):
    order = get_object_or_404(
        Order.objects.prefetch_related("items__product"), pk=order_id, user=request.user
    )
    items = list(order.items.all())
    if not items:
        messages.error(request, "This order has no items to reorder.")
        return redirect("bakery:order_history")
    if any(not item.product.is_active or not item.product.branch.is_active for item in items):
        messages.error(request, "One or more items from this order are no longer available.")
        return redirect("bakery:order_history")
    branch_ids = {item.product.branch_id for item in items}
    if len(branch_ids) != 1:
        messages.error(request, "This order cannot be reordered because its products span branches.")
        return redirect("bakery:order_history")
    request.session["cart"] = {
        str(item.product_id): item.quantity for item in items if item.quantity <= 99
    }
    if len(request.session["cart"]) != len(items):
        messages.error(request, "This order contains quantities that cannot be reordered.")
        return redirect("bakery:order_history")
    request.session.modified = True
    messages.success(request, "Items added to your basket. Review availability and prices at checkout.")
    return redirect("bakery:checkout")


@login_required
def order_detail(request, order_id):
    order = get_object_or_404(Order.objects.select_related("branch", "user"), pk=order_id)
    if not _can_view_order(request.user, order):
        raise Http404
    return render(request, "bakery/order_detail.html", {"order": order})


def _can_view_order(user, order):
    if order.user_id == user.pk or user.role == User.Role.ADMIN or user.is_superuser:
        return True
    return user.role in (User.Role.BRANCH_MANAGER, User.Role.DISPATCHER) and user.branch_id == order.branch_id


def _staff_orders(user):
    orders = Order.objects.select_related("user", "branch")
    if user.role == User.Role.ADMIN or user.is_superuser:
        return orders
    if user.role in (User.Role.BRANCH_MANAGER, User.Role.DISPATCHER) and user.branch_id:
        return orders.filter(branch_id=user.branch_id)
    raise Http404


@login_required
def staff_queue(request):
    if request.user.role == User.Role.CUSTOMER:
        raise Http404
    orders = _staff_orders(request.user).exclude(
        status__in=(Order.Status.CANCELLED, Order.Status.DELIVERED)
    )
    return render(request, "bakery/staff_queue.html", {"orders": orders})


@login_required
@require_POST
def update_order_status(request, order_id):
    if request.user.role == User.Role.CUSTOMER:
        raise Http404
    order = get_object_or_404(_staff_orders(request.user), pk=order_id)
    new_status = request.POST.get("status", "")
    allowed_for_role = {
        User.Role.BRANCH_MANAGER: {Order.Status.BAKING, Order.Status.CANCELLED},
        User.Role.DISPATCHER: {Order.Status.DISPATCHED},
        User.Role.ADMIN: {
            Order.Status.BAKING, Order.Status.DISPATCHED, Order.Status.CANCELLED,
        },
    }
    if new_status not in allowed_for_role.get(request.user.role, set()):
        messages.error(request, "You are not allowed to set that order status.")
        return redirect("bakery:staff_queue")
    try:
        transition_order(order=order, new_status=new_status, actor=request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, f"Order {order.order_number} updated.")
    return redirect("bakery:staff_queue")


@login_required
@require_GET
def dispatch_verification_page(request):
    if request.user.role != User.Role.DISPATCHER or not request.user.branch_id:
        raise Http404
    return render(request, "bakery/dispatch_verify.html")


@login_required
@require_POST
def verify_dispatch(request):
    if request.user.role != User.Role.DISPATCHER or not request.user.branch_id:
        raise Http404
    token = request.POST.get("token", "").strip()
    try:
        order = verify_dispatch_token(token=token, dispatcher=request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("bakery:dispatch_verification")
    messages.success(request, f"Delivery verified for order {order.order_number}.")
    return redirect("bakery:dispatch_verification")


@csrf_exempt
@require_POST
def run_subscription_job(request):
    configured_secret = settings.CRON_SECRET
    supplied = request.headers.get("Authorization", "")
    if not configured_secret:
        return JsonResponse({"status": "unavailable"}, status=503)
    expected = f"Bearer {configured_secret}"
    if not secrets.compare_digest(supplied, expected):
        return JsonResponse({"status": "unauthorized"}, status=401)
    result = process_due_subscriptions()
    failed = result["failed"]
    return JsonResponse(
        {
            "created": len(result["created"]),
            "failed": failed,
        },
        status=500 if failed else 200,
    )
