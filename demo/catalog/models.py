"""Catalogue: products, variants, pricing and suppliers."""

from django.db import models


class Category(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children"
    )
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return self.name


class Brand(models.Model):
    name = models.CharField(max_length=120, unique=True)
    country = models.CharField(max_length=2, blank=True)
    website = models.URLField(blank=True)

    def __str__(self) -> str:
        return self.name


class Product(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    sku = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    brand = models.ForeignKey(
        Brand, on_delete=models.SET_NULL, null=True, blank=True, related_name="products"
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["category", "name"], name="uq_product_category_name")
        ]

    def __str__(self) -> str:
        return self.name


class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    sku = models.CharField(max_length=64, unique=True)
    barcode = models.CharField(max_length=32, blank=True)
    price_cents = models.PositiveIntegerField()
    compare_at_cents = models.PositiveIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="EUR")
    weight_g = models.PositiveIntegerField(null=True, blank=True)
    is_default = models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.sku


class ProductMedia(models.Model):
    # Doctor bait: a foreign key with no index behind it.
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.CASCADE, related_name="media", db_index=False
    )
    url = models.URLField()
    kind = models.CharField(max_length=16, default="image")
    position = models.PositiveSmallIntegerField(default=0)


class PriceList(models.Model):
    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    currency = models.CharField(max_length=3, default="EUR")
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)

    def __str__(self) -> str:
        return self.code


class PriceListItem(models.Model):
    price_list = models.ForeignKey(PriceList, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name="price_items")
    amount_cents = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["price_list", "variant"], name="uq_pricelist_variant")
        ]


class Supplier(models.Model):
    name = models.CharField(max_length=200)
    vat_number = models.CharField(max_length=32, unique=True)
    email = models.EmailField(blank=True)
    # Doctor bait: money kept as a float.
    outstanding_balance = models.FloatField(default=0.0)
    lead_time_days = models.PositiveSmallIntegerField(default=0)
    is_preferred = models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.name
