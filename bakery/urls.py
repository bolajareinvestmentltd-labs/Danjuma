from django.urls import path
from django.contrib.auth import views as auth_views

from . import views

app_name = "bakery"

urlpatterns = [
    path("", views.storefront, name="storefront"),
    path("api/health/", views.health, name="health"),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="bakery/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/register/", views.register, name="register"),
    path("accounts/addresses/", views.address_book, name="address_book"),
    path("accounts/addresses/<int:address_id>/delete/", views.delete_address, name="delete_address"),
    path("cart/add/<int:product_id>/", views.add_to_cart, name="add_to_cart"),
    path("cart/update/<int:product_id>/", views.update_cart, name="update_cart"),
    path("checkout/", views.checkout, name="checkout"),
    path("orders/", views.order_history, name="order_history"),
    path("orders/<int:order_id>/", views.order_detail, name="order_detail"),
    path("orders/<int:order_id>/reorder/", views.reorder, name="reorder"),
    path("staff/orders/", views.staff_queue, name="staff_queue"),
    path("staff/orders/<int:order_id>/status/", views.update_order_status, name="update_order_status"),
    path("staff/dispatch/verify/", views.dispatch_verification_page, name="dispatch_verification"),
    path("staff/dispatch/verify/submit/", views.verify_dispatch, name="verify_dispatch"),
    path("api/cron/subscriptions/", views.run_subscription_job, name="subscription_job"),
]