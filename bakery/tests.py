from django.test import TestCase
from django.urls import reverse

from .models import Branch, Product


class StorefrontTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            name="Wuse Bakery",
            state="FCT",
            city="Abuja",
            address="Wuse, Abuja",
        )
        self.milk_bread = Product.objects.create(
            branch=self.branch,
            title="Danjuma Special Milk Bread",
            category=Product.Category.LOAVES,
            description="Soft, freshly baked family loaf.",
            price="1200.00",
            stock_qty=10,
        )
        Product.objects.create(
            branch=self.branch,
            title="Butter Croissants",
            category=Product.Category.PASTRIES,
            description="Flaky pastry baked fresh.",
            price="2000.00",
            stock_qty=8,
        )

    def test_storefront_lists_active_products(self):
        response = self.client.get(reverse("bakery:storefront"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.milk_bread.title)
        self.assertContains(response, "Butter Croissants")

    def test_storefront_filters_by_known_category(self):
        response = self.client.get(reverse("bakery:storefront"), {"category": "pastries"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Butter Croissants")
        self.assertNotContains(response, self.milk_bread.title)

    def test_unknown_category_does_not_break_storefront(self):
        response = self.client.get(reverse("bakery:storefront"), {"category": "unknown"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.milk_bread.title)

    def test_health_endpoint_checks_database(self):
        response = self.client.get(reverse("bakery:health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "database": "ok"})
