from django.urls import include, path

from bakery.admin import bakery_admin_site

urlpatterns = [
    path("admin/", bakery_admin_site.urls),
    path("", include("bakery.urls")),
]
