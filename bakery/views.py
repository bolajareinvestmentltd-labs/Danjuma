from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import Branch, Product


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
