from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.admin import AdminSite

from .models import (
    Branch,
    CustomerAddress,
    Order,
    OrderItem,
    OrderStatusHistory,
    PaymentTransaction,
    Product,
    Subscription,
    SubscriptionItem,
    SubscriptionPreparation,
    User as BakeryUser,
)

class BakeryAdminSite(AdminSite):
    site_header = "Danjuma Bread operations"
    site_title = "Danjuma Bread admin"
    index_title = "Bakery management"

    def has_permission(self, request):
        user = request.user
        return (
            user.is_active
            and user.is_staff
            and (user.is_superuser or user.role == BakeryUser.Role.ADMIN)
        )


bakery_admin_site = BakeryAdminSite(name="admin")


@admin.register(BakeryUser, site=bakery_admin_site)
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


@admin.register(Branch, site=bakery_admin_site)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "state", "phone", "is_active")
    list_filter = ("state", "is_active")
    search_fields = ("name", "city", "address")


@admin.register(Product, site=bakery_admin_site)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("title", "branch", "category", "price", "stock_qty", "is_active")
    list_filter = ("branch", "category", "is_active")
    search_fields = ("title", "description")


@admin.register(CustomerAddress, site=bakery_admin_site)
class CustomerAddressAdmin(admin.ModelAdmin):
    list_display = ("recipient_name", "user", "label", "city", "state", "is_default")
    list_filter = ("state", "is_default")
    search_fields = ("recipient_name", "user__email", "phone", "address")


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = ("product", "title_snapshot", "quantity", "unit_price")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order, site=bakery_admin_site)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("order_number", "user", "branch", "status", "total_amount", "created_at")
    list_filter = ("branch", "status", "fulfillment_type", "created_at")
    search_fields = ("order_number", "user__email")
    readonly_fields = (
        "order_number", "user", "branch", "fulfillment_type", "total_amount", "service_fee",
        "status", "delivery_address", "scheduled_date", "scheduled_time_slot",
        "slicing_preference", "qr_code_payload", "inventory_released", "created_at",
        "updated_at", "delivered_at",
    )
    inlines = (OrderItemInline,)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

class SubscriptionItemInline(admin.TabularInline):
    model = SubscriptionItem
    extra = 1


@admin.register(Subscription, site=bakery_admin_site)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "branch", "frequency", "next_delivery_date", "is_active")
    list_filter = ("branch", "frequency", "is_active")
    inlines = (SubscriptionItemInline,)


@admin.register(SubscriptionPreparation, site=bakery_admin_site)
class SubscriptionPreparationAdmin(admin.ModelAdmin):
    list_display = ("subscription", "order", "delivery_date", "created_at")
    readonly_fields = ("subscription", "order", "delivery_date", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OrderStatusHistory, site=bakery_admin_site)
class OrderStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("order", "old_status", "new_status", "changed_by", "created_at")
    list_filter = ("new_status", "created_at")
    search_fields = ("order__order_number", "changed_by__email")
    readonly_fields = ("order", "old_status", "new_status", "changed_by", "note", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PaymentTransaction, site=bakery_admin_site)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ("reference", "order", "provider", "amount", "status", "created_at")
    list_filter = ("provider", "status", "created_at")
    search_fields = ("reference", "order__order_number")
    readonly_fields = (
        "order", "provider", "reference", "account_no", "amount", "status",
        "raw_webhook_data", "created_at", "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
