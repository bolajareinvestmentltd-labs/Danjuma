from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    Branch,
    Order,
    OrderItem,
    PaymentTransaction,
    Product,
    Subscription,
    SubscriptionItem,
    User as BakeryUser,
)


@admin.register(BakeryUser)
class BakeryUserAdmin(UserAdmin):
    ordering = ("email",)
    list_display = ("email", "name", "role", "branch", "is_active", "is_staff")
    list_filter = ("role", "branch", "is_active", "is_staff")
    search_fields = ("email", "name", "phone")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal details", {"fields": ("name", "phone", "avatar_url", "role", "branch")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "name", "role", "password1", "password2")}),
    )
    filter_horizontal = ("groups", "user_permissions")


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "state", "phone", "is_active")
    list_filter = ("state", "is_active")
    search_fields = ("name", "city", "address")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("title", "branch", "category", "price", "stock_qty", "is_active")
    list_filter = ("branch", "category", "is_active")
    search_fields = ("title", "description")


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("title_snapshot", "quantity", "unit_price")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("order_number", "user", "branch", "status", "total_amount", "created_at")
    list_filter = ("branch", "status", "fulfillment_type", "created_at")
    search_fields = ("order_number", "user__email")
    readonly_fields = ("order_number", "created_at", "updated_at", "delivered_at")
    inlines = (OrderItemInline,)


class SubscriptionItemInline(admin.TabularInline):
    model = SubscriptionItem
    extra = 1


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "branch", "frequency", "next_delivery_date", "is_active")
    list_filter = ("branch", "frequency", "is_active")
    inlines = (SubscriptionItemInline,)


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ("reference", "order", "provider", "amount", "status", "created_at")
    list_filter = ("provider", "status", "created_at")
    search_fields = ("reference", "order__order_number")
    readonly_fields = ("raw_webhook_data", "created_at", "updated_at")
