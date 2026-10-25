from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.test import override_settings

from .models import (
    Branch,
    CustomerAddress,
    Order,
    OrderStatusHistory,
    Product,
    Subscription,
    SubscriptionItem,
    SubscriptionPreparation,
    WebhookEvent,
)
from .services import (
    create_order,
    process_due_subscriptions,
    transition_order,
    verify_dispatch_token,
)

User = get_user_model()


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
        self.assertContains(response, "/static/bakery/site.css")

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


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class OrderingAndAccessTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            name="Wuse Bakery", state="FCT", city="Abuja", address="Wuse, Abuja"
        )
        self.other_branch = Branch.objects.create(
            name="Garki Bakery", state="FCT", city="Abuja", address="Garki, Abuja"
        )
        self.product = Product.objects.create(
            branch=self.branch,
            title="Milk Bread",
            category=Product.Category.LOAVES,
            price=Decimal("1200.00"),
            stock_qty=10,
        )
        self.customer = User.objects.create_user(
            email="customer@example.com", password="Strong-password-123"
        )
        self.manager = User.objects.create_user(
            email="manager@example.com",
            password="Strong-password-123",
            role=User.Role.BRANCH_MANAGER,
            branch=self.branch,
        )

    def _set_cart(self, items):
        session = self.client.session
        session["cart"] = items
        session.save()

    def test_checkout_requires_authentication(self):
        response = self.client.get(reverse("bakery:checkout"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_registration_creates_customer_without_staff_access(self):
        response = self.client.post(
            reverse("bakery:register"),
            {
                "email": "new@example.com",
                "name": "New Customer",
                "phone": "08000000000",
                "password1": "Safe-Passphrase-927!",
                "password2": "Safe-Passphrase-927!",
            },
        )

        self.assertRedirects(response, reverse("bakery:storefront"))
        user = User.objects.get(email="new@example.com")
        self.assertEqual(user.role, User.Role.CUSTOMER)
        self.assertFalse(user.is_staff)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_saved_addresses_keep_one_default_and_cannot_be_cross_deleted(self):
        self.client.force_login(self.customer)
        address_data = {
            "label": "Home",
            "recipient_name": "Customer",
            "phone": "08000000000",
            "address": "12 Baker Street",
            "city": "Abuja",
            "state": "FCT",
            "is_default": "",
        }
        self.client.post(reverse("bakery:address_book"), address_data)
        first = CustomerAddress.objects.get(user=self.customer, label="Home")
        self.assertTrue(first.is_default)

        second_data = {**address_data, "label": "Office", "address": "8 Market Road"}
        self.client.post(reverse("bakery:address_book"), second_data)
        second = CustomerAddress.objects.get(user=self.customer, label="Office")
        self.assertFalse(second.is_default)

        third_data = {**address_data, "label": "Work", "is_default": "on"}
        self.client.post(reverse("bakery:address_book"), third_data)
        third = CustomerAddress.objects.get(user=self.customer, label="Work")
        third.refresh_from_db()
        first.refresh_from_db()
        self.assertTrue(third.is_default)
        self.assertFalse(first.is_default)

        other = User.objects.create_user(
            email="other@example.com", password="Strong-password-123"
        )
        other_address = CustomerAddress.objects.create(
            user=other,
            recipient_name="Other",
            phone="08000000001",
            address="Other Road",
            city="Abuja",
            state="FCT",
        )
        response = self.client.post(
            reverse("bakery:delete_address", args=(other_address.pk,))
        )
        self.assertEqual(response.status_code, 404)

    def test_checkout_can_select_an_owned_saved_address(self):
        address = CustomerAddress.objects.create(
            user=self.customer,
            label="Home",
            recipient_name="Customer",
            phone="08000000000",
            address="12 Baker Street",
            city="Abuja",
            state="FCT",
            is_default=True,
        )
        self.client.force_login(self.customer)
        self._set_cart({str(self.product.pk): "1"})

        response = self.client.post(
            reverse("bakery:checkout"),
            {
                "fulfillment_type": Order.FulfillmentType.DELIVERY,
                "delivery_address": "",
                "saved_address": str(address.pk),
            },
        )

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get(user=self.customer)
        self.assertIn("12 Baker Street", order.delivery_address)
        self.assertIn("08000000000", order.delivery_address)

    def test_reorder_restores_only_the_customers_original_items(self):
        order = create_order(
            user=self.customer,
            cart={str(self.product.pk): 2},
            fulfillment_type=Order.FulfillmentType.PICKUP,
        )
        self.client.force_login(self.customer)

        response = self.client.post(reverse("bakery:reorder", args=(order.pk,)))

        self.assertRedirects(response, reverse("bakery:checkout"))
        self.assertEqual(self.client.session["cart"], {str(self.product.pk): 2})
        other_user = User.objects.create_user(
            email="other@example.com", password="Strong-password-123"
        )
        other_order = create_order(
            user=other_user,
            cart={str(self.product.pk): 1},
            fulfillment_type=Order.FulfillmentType.PICKUP,
        )
        response = self.client.post(reverse("bakery:reorder", args=(other_order.pk,)))
        self.assertEqual(response.status_code, 404)

    @override_settings(DELIVERY_SERVICE_FEE=Decimal("150.00"))
    def test_checkout_uses_server_price_and_reserves_stock(self):
        self.client.force_login(self.customer)
        self._set_cart({str(self.product.pk): "2"})

        response = self.client.post(
            reverse("bakery:checkout"),
            {
                "fulfillment_type": Order.FulfillmentType.DELIVERY,
                "delivery_address": "12 Baker Street, Abuja",
                "total_amount": "1.00",
                "service_fee": "0.00",
            },
        )

        order = Order.objects.get(user=self.customer)
        self.assertRedirects(response, reverse("bakery:order_detail", args=(order.pk,)))
        self.assertEqual(order.total_amount, Decimal("2550.00"))
        self.assertEqual(order.service_fee, Decimal("150.00"))
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(order.items.get().unit_price, Decimal("1200.00"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_qty, 8)
        self.assertEqual(order.status_history.count(), 1)

    def test_checkout_rejects_insufficient_stock_without_creating_order(self):
        self.client.force_login(self.customer)
        self._set_cart({str(self.product.pk): "11"})

        response = self.client.post(
            reverse("bakery:checkout"),
            {"fulfillment_type": Order.FulfillmentType.PICKUP},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Order.objects.exists())
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_qty, 10)

    def test_cart_rejects_products_from_multiple_branches(self):
        other_product = Product.objects.create(
            branch=self.other_branch,
            title="Other Loaf",
            category=Product.Category.LOAVES,
            price=Decimal("900.00"),
            stock_qty=5,
        )
        self.client.post(reverse("bakery:add_to_cart", args=(self.product.pk,)))
        response = self.client.post(reverse("bakery:add_to_cart", args=(other_product.pk,)))

        self.assertRedirects(response, reverse("bakery:storefront"))
        self.assertEqual(self.client.session["cart"], {str(self.product.pk): 1})

    def test_cancellation_restores_reserved_stock_once_and_is_audited(self):
        order = create_order(
            user=self.customer,
            cart={str(self.product.pk): 3},
            fulfillment_type=Order.FulfillmentType.PICKUP,
        )
        transition_order(order=order, new_status=Order.Status.CANCELLED, actor=self.manager)

        self.product.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(self.product.stock_qty, 10)
        self.assertTrue(order.inventory_released)
        self.assertEqual(
            list(order.status_history.values_list("new_status", flat=True)),
            [Order.Status.PENDING, Order.Status.CANCELLED],
        )
        with self.assertRaises(ValidationError):
            transition_order(order=order, new_status=Order.Status.CANCELLED, actor=self.manager)

    def test_branch_staff_cannot_read_other_branch_order(self):
        order = create_order(
            user=self.customer,
            cart={str(self.product.pk): 1},
            fulfillment_type=Order.FulfillmentType.PICKUP,
        )
        self.client.force_login(self.manager)

        response = self.client.get(reverse("bakery:order_detail", args=(order.pk,)))

        self.assertEqual(response.status_code, 200)

        other_product = Product.objects.create(
            branch=self.other_branch,
            title="Garki Loaf",
            category=Product.Category.LOAVES,
            price=Decimal("1000.00"),
            stock_qty=5,
        )
        other_order = create_order(
            user=self.customer,
            cart={str(other_product.pk): 1},
            fulfillment_type=Order.FulfillmentType.PICKUP,
        )
        response = self.client.get(reverse("bakery:order_detail", args=(other_order.pk,)))
        self.assertEqual(response.status_code, 404)

    def test_staff_queue_is_scoped_to_staff_branch(self):
        own_order = create_order(
            user=self.customer,
            cart={str(self.product.pk): 1},
            fulfillment_type=Order.FulfillmentType.PICKUP,
        )
        other_product = Product.objects.create(
            branch=self.other_branch,
            title="Garki Loaf",
            category=Product.Category.LOAVES,
            price=Decimal("1000.00"),
            stock_qty=5,
        )
        other_order = create_order(
            user=self.customer,
            cart={str(other_product.pk): 1},
            fulfillment_type=Order.FulfillmentType.PICKUP,
        )
        self.client.force_login(self.manager)

        response = self.client.get(reverse("bakery:staff_queue"))

        self.assertContains(response, own_order.order_number)
        self.assertNotContains(response, other_order.order_number)

    def test_branch_staff_cannot_access_global_admin(self):
        self.manager.is_staff = True
        self.manager.save(update_fields=("is_staff",))
        self.client.force_login(self.manager)

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)

    def test_pending_payment_cannot_be_marked_paid_by_staff_view(self):
        order = create_order(
            user=self.customer,
            cart={str(self.product.pk): 1},
            fulfillment_type=Order.FulfillmentType.PICKUP,
        )
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("bakery:update_order_status", args=(order.pk,)),
            {"status": Order.Status.PAID},
        )

        self.assertRedirects(response, reverse("bakery:staff_queue"))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)

    def test_webhook_event_provider_reference_is_unique(self):
        WebhookEvent.objects.create(provider=WebhookEvent.Provider.PAYSTACK, event_id="evt-1", payload={})

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                WebhookEvent.objects.create(
                    provider=WebhookEvent.Provider.PAYSTACK, event_id="evt-1", payload={}
                )

    def test_confirmed_delivery_gets_branch_bound_single_use_dispatch_token(self):
        order = create_order(
            user=self.customer,
            cart={str(self.product.pk): 1},
            fulfillment_type=Order.FulfillmentType.DELIVERY,
            delivery_address="12 Baker Street, Abuja",
        )
        transition_order(order=order, new_status=Order.Status.PAID, actor=None)
        order.refresh_from_db()
        self.assertTrue(order.qr_code_payload)

        transition_order(order=order, new_status=Order.Status.BAKING, actor=self.manager)
        dispatcher = User.objects.create_user(
            email="rider@example.com",
            password="Strong-password-123",
            role=User.Role.DISPATCHER,
            branch=self.branch,
        )
        transition_order(order=order, new_status=Order.Status.DISPATCHED, actor=self.manager)
        wrong_branch_dispatcher = User.objects.create_user(
            email="other-rider@example.com",
            password="Strong-password-123",
            role=User.Role.DISPATCHER,
            branch=self.other_branch,
        )
        with self.assertRaises(ValidationError):
            verify_dispatch_token(
                token=order.qr_code_payload, dispatcher=wrong_branch_dispatcher
            )
        delivered = verify_dispatch_token(
            token=order.qr_code_payload, dispatcher=dispatcher
        )

        self.assertEqual(delivered.status, Order.Status.DELIVERED)
        self.assertIsNotNone(delivered.delivered_at)
        with self.assertRaises(ValidationError):
            verify_dispatch_token(token=order.qr_code_payload, dispatcher=dispatcher)

    def test_tampered_dispatch_token_is_rejected(self):
        order = create_order(
            user=self.customer,
            cart={str(self.product.pk): 1},
            fulfillment_type=Order.FulfillmentType.DELIVERY,
            delivery_address="12 Baker Street, Abuja",
        )
        transition_order(order=order, new_status=Order.Status.PAID, actor=None)
        dispatcher = User.objects.create_user(
            email="rider@example.com",
            password="Strong-password-123",
            role=User.Role.DISPATCHER,
            branch=self.branch,
        )

        with self.assertRaises(ValidationError):
            verify_dispatch_token(
                token=f"{order.qr_code_payload}tampered", dispatcher=dispatcher
            )

    def test_subscription_job_creates_idempotent_preparation_not_payment(self):
        today = date.today()
        subscription = Subscription.objects.create(
            user=self.customer,
            branch=self.branch,
            frequency=Subscription.Frequency.DAILY,
            preferred_time=time(6, 30),
            next_delivery_date=today,
            delivery_address="12 Baker Street, Abuja",
        )
        SubscriptionItem.objects.create(
            subscription=subscription, product=self.product, quantity=2
        )

        result = process_due_subscriptions(today=today)
        repeated = process_due_subscriptions(today=today)

        self.assertEqual(len(result["created"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(repeated["created"], [])
        order = result["created"][0]
        self.assertEqual(order.status, Order.Status.PREPARATION_QUEUED)
        self.assertEqual(order.scheduled_date, today)
        self.assertEqual(order.payments.count(), 0)
        self.assertEqual(SubscriptionPreparation.objects.filter(subscription=subscription).count(), 1)
        subscription.refresh_from_db()
        self.assertEqual(subscription.next_delivery_date, today + timedelta(days=1))

    def test_failed_subscription_preparation_does_not_advance_schedule_or_reserve_stock(self):
        today = date.today()
        self.product.stock_qty = 0
        self.product.save(update_fields=("stock_qty",))
        subscription = Subscription.objects.create(
            user=self.customer,
            branch=self.branch,
            frequency=Subscription.Frequency.WEEKLY,
            preferred_time=time(7, 0),
            next_delivery_date=today,
        )
        SubscriptionItem.objects.create(
            subscription=subscription, product=self.product, quantity=1
        )

        result = process_due_subscriptions(today=today)

        self.assertEqual(result["created"], [])
        self.assertEqual(len(result["failed"]), 1)
        self.assertFalse(Order.objects.exists())
        self.assertFalse(SubscriptionPreparation.objects.exists())
        subscription.refresh_from_db()
        self.assertEqual(subscription.next_delivery_date, today)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_qty, 0)

    @override_settings(CRON_SECRET="local-test-secret")
    def test_subscription_cron_requires_bearer_secret(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        unauthorized = client.post(reverse("bakery:subscription_job"))
        self.assertEqual(unauthorized.status_code, 401)
        authorized = client.post(
            reverse("bakery:subscription_job"),
            HTTP_AUTHORIZATION="Bearer local-test-secret",
        )
        self.assertEqual(authorized.status_code, 200)
        self.assertEqual(authorized.json(), {"created": 0, "failed": []})
