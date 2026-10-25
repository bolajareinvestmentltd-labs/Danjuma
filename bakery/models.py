from secrets import token_hex

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


def generate_order_number():
    return f"DB-{token_hex(5).upper()}"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)
        if not extra_fields["is_staff"] or not extra_fields["is_superuser"]:
            raise ValueError("A superuser must have is_staff and is_superuser enabled.")
        return self.create_user(email, password, **extra_fields)


class Branch(models.Model):
    name = models.CharField(max_length=120)
    state = models.CharField(max_length=80)
    city = models.CharField(max_length=80)
    address = models.CharField(max_length=255)
    phone = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return f"{self.name} — {self.city}"


class User(AbstractUser):
    class Role(models.TextChoices):
        CUSTOMER = "CUSTOMER", "Customer"
        BRANCH_MANAGER = "BRANCH_MANAGER", "Branch manager"
        DISPATCHER = "DISPATCHER", "Dispatcher"
        ADMIN = "ADMIN", "Administrator"

    username = None
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=160, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    avatar_url = models.URLField(max_length=500, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER)
    branch = models.ForeignKey(
        Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="staff"
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UserManager()

    def __str__(self):
        return self.name or self.email


class Product(models.Model):
    class Category(models.TextChoices):
        LOAVES = "LOAVES", "Loaves & family"
        ARTISANAL = "ARTISANAL", "Artisanal & sourdough"
        PASTRIES = "PASTRIES", "Pastries & rolls"
        SUBSCRIPTIONS = "SUBSCRIPTIONS", "Subscriptions"
        OTHER = "OTHER", "Other"

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="products")
    title = models.CharField(max_length=160)
    category = models.CharField(max_length=20, choices=Category.choices)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    wholesale_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    min_wholesale_qty = models.PositiveIntegerField(default=1)
    stock_qty = models.PositiveIntegerField(default=0)
    image_url = models.URLField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("category", "title")
        indexes = [models.Index(fields=("branch", "is_active", "category"))]

    def __str__(self):
        return self.title


class Order(models.Model):
    class FulfillmentType(models.TextChoices):
        DELIVERY = "DELIVERY", "Delivery"
        PICKUP = "PICKUP", "Pickup"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending payment"
        PAID = "PAID", "Paid"
        BAKING = "BAKING", "Baking"
        DISPATCHED = "DISPATCHED", "Dispatched"
        DELIVERED = "DELIVERED", "Delivered"
        CANCELLED = "CANCELLED", "Cancelled"

    order_number = models.CharField(max_length=24, unique=True, default=generate_order_number)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="orders")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="orders")
    fulfillment_type = models.CharField(max_length=10, choices=FulfillmentType.choices)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    service_fee = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    delivery_address = models.TextField(blank=True)
    scheduled_date = models.DateField(null=True, blank=True)
    scheduled_time_slot = models.CharField(max_length=80, blank=True)
    slicing_preference = models.CharField(max_length=40, default="Unsliced")
    qr_code_payload = models.TextField(blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("branch", "status", "created_at"))]

    def __str__(self):
        return self.order_number


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_items")
    title_snapshot = models.CharField(max_length=160)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])

    def __str__(self):
        return f"{self.quantity} × {self.title_snapshot}"


class Subscription(models.Model):
    class Frequency(models.TextChoices):
        DAILY = "DAILY", "Daily"
        WEEKLY = "WEEKLY", "Weekly"
        BIWEEKLY = "BIWEEKLY", "Every two weeks"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="subscriptions")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="subscriptions")
    frequency = models.CharField(max_length=10, choices=Frequency.choices)
    preferred_time = models.TimeField()
    slicing_preference = models.CharField(max_length=40, default="Unsliced")
    is_active = models.BooleanField(default=True)
    next_delivery_date = models.DateField(db_index=True)
    delivery_address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("next_delivery_date",)
        indexes = [models.Index(fields=("is_active", "next_delivery_date"))]

    def __str__(self):
        return f"{self.user} — {self.get_frequency_display()}"


class SubscriptionItem(models.Model):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="subscription_items")
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("subscription", "product"), name="unique_subscription_product"
            )
        ]


class PaymentTransaction(models.Model):
    class Provider(models.TextChoices):
        ALATPAY = "ALATPAY", "ALATPay"
        PAYSTACK = "PAYSTACK", "Paystack"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank transfer"

    class Status(models.TextChoices):
        INITIATED = "INITIATED", "Initiated"
        SUCCESS = "SUCCESS", "Successful"
        FAILED = "FAILED", "Failed"

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payments")
    provider = models.CharField(max_length=20, choices=Provider.choices)
    reference = models.CharField(max_length=120, unique=True)
    account_no = models.CharField(max_length=32, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.INITIATED)
    raw_webhook_data = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.provider}: {self.reference}"
