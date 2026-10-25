from django.core.management.base import BaseCommand, CommandError

from bakery.services import process_due_subscriptions


class Command(BaseCommand):
    help = "Create idempotent kitchen-preparation orders for due subscriptions."

    def handle(self, *args, **options):
        result = process_due_subscriptions()
        for order in result["created"]:
            self.stdout.write(f"Created preparation order {order.order_number}.")
        for failure in result["failed"]:
            self.stderr.write(
                f"Subscription {failure['subscription_id']}: {failure['reason']}"
            )
        if result["failed"]:
            raise CommandError(
                f"{len(result['failed'])} due subscription(s) could not be processed."
            )
        self.stdout.write(f"Processed {len(result['created'])} due subscription(s).")
