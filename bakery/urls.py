from django.urls import path

from . import views

app_name = "bakery"

urlpatterns = [
    path("", views.storefront, name="storefront"),
    path("api/health/", views.health, name="health"),
]