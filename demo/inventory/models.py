"""Stock on hand, movements and replenishment."""

from django.db import models

from catalog.models import ProductVariant


class Warehouse(models.Model):
    code = models.SlugField(max_length=16, unique=True)
    name = models.CharField(max_length=120)
    country = models.CharField(max_length=2)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.code


class StockItem(models.Model):
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name="stock_items")
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name="stock_items")
    quantity = models.IntegerField(default=0)
    reserved = models.IntegerField(default=0)
    reorder_point = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["warehouse", "variant"], name="uq_stock_warehouse_variant"),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0), name="ck_stock_quantity_non_negative"
            ),
        ]


class StockMovement(models.Model):
    class Kind(models.TextChoices):
        RECEIPT = "receipt", "Receipt"
        PICK = "pick", "Pick"
        ADJUSTMENT = "adjustment", "Adjustment"
        RETURN = "return", "Return"

    stock_item = models.ForeignKey(StockItem, on_delete=models.CASCADE, related_name="movements")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    quantity = models.IntegerField()
    reference = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class StockTransfer(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        IN_TRANSIT = "in_transit", "In transit"
        RECEIVED = "received", "Received"
        CANCELLED = "cancelled", "Cancelled"

    reference = models.CharField(max_length=32, unique=True)
    from_warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="transfers_out"
    )
    to_warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="transfers_in"
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    received_at = models.DateTimeField(null=True, blank=True)


class StockTransferLine(models.Model):
    transfer = models.ForeignKey(StockTransfer, on_delete=models.CASCADE, related_name="lines")
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name="transfer_lines")
    quantity = models.PositiveIntegerField()


class ReorderRule(models.Model):
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name="reorder_rules")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE)
    min_quantity = models.PositiveIntegerField(default=0)
    max_quantity = models.PositiveIntegerField(default=0)
    supplier = models.ForeignKey(
        "catalog.Supplier", on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["variant", "warehouse"], name="uq_reorder_variant_wh")
        ]
