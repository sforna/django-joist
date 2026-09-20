"""Customers, orders, fulfilment and billing."""

from django.db import models

from catalog.models import ProductVariant
from inventory.models import Warehouse


class Customer(models.Model):
    class Segment(models.TextChoices):
        RETAIL = "retail", "Retail"
        BUSINESS = "business", "Business"
        RESELLER = "reseller", "Reseller"

    name = models.CharField(max_length=200)
    email = models.EmailField(unique=True)
    tax_code = models.CharField(max_length=32, blank=True)
    segment = models.CharField(max_length=16, choices=Segment.choices, default=Segment.RETAIL)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class CustomerAddress(models.Model):
    class Kind(models.TextChoices):
        BILLING = "billing", "Billing"
        SHIPPING = "shipping", "Shipping"

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="addresses")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    street = models.CharField(max_length=255)
    city = models.CharField(max_length=120)
    postal_code = models.CharField(max_length=16)
    country = models.CharField(max_length=2)
    is_default = models.BooleanField(default=False)


class SalesOrder(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        CONFIRMED = "confirmed", "Confirmed"
        SHIPPED = "shipped", "Shipped"
        CANCELLED = "cancelled", "Cancelled"

    number = models.CharField(max_length=32, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    placed_at = models.DateTimeField()
    currency = models.CharField(max_length=3, default="EUR")
    total_cents = models.BigIntegerField(default=0)
    note = models.TextField(blank=True)

    class Meta:
        indexes = [models.Index(fields=["customer", "placed_at"], name="sales_order_cust_placed_idx")]


class OrderLine(models.Model):
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="lines")
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name="order_lines")
    quantity = models.PositiveIntegerField()
    unit_price_cents = models.PositiveIntegerField()
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)


class Shipment(models.Model):
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="shipments")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    carrier = models.CharField(max_length=64)
    tracking_number = models.CharField(max_length=64, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)


class Invoice(models.Model):
    order = models.OneToOneField(SalesOrder, on_delete=models.PROTECT, related_name="invoice")
    number = models.CharField(max_length=32, unique=True)
    issued_at = models.DateField()
    due_at = models.DateField()
    paid_at = models.DateField(null=True, blank=True)
    amount_cents = models.BigIntegerField()
    tax_cents = models.BigIntegerField(default=0)


class OrderEvent(models.Model):
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=32)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["order", "created_at"], name="sales_orderevent_order_idx")]


class Payment(models.Model):
    class Method(models.TextChoices):
        CARD = "card", "Card"
        TRANSFER = "transfer", "Bank transfer"
        CASH = "cash", "Cash"

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="payments")
    method = models.CharField(max_length=16, choices=Method.choices)
    amount_cents = models.BigIntegerField()
    reference = models.CharField(max_length=64, blank=True)
    received_at = models.DateTimeField()
