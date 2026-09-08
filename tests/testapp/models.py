"""Model fixtures exercising every structural case the snapshot must carry:
plain tables, FKs with actions, composite unique constraints, explicit
indexes, generic (polymorphic) relations, pivot tables, defaults, nullable,
and a table with deliberate doctor-bait problems (no PK on a plain table is
impossible via Django models; raw SQL in a migration covers that later)."""

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class Author(models.Model):
    name = models.CharField(max_length=200)
    email = models.EmailField(unique=True)
    bio = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Publisher(models.Model):
    name = models.CharField(max_length=255)
    # Doctor bait: money stored as a float.
    balance = models.FloatField(default=0.0)


class Book(models.Model):
    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="books")
    publisher = models.ForeignKey(
        Publisher, on_delete=models.SET_NULL, null=True, related_name="books"
    )
    title = models.CharField(max_length=255)
    price_cents = models.PositiveIntegerField(null=True, default=0)
    is_published = models.BooleanField(default=False)
    data = models.JSONField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["author", "title"], name="uq_book_author_title")
        ]


class Tag(models.Model):
    slug = models.SlugField()

    class Meta:
        indexes = [models.Index(fields=["slug"])]


class BookTag(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE)
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["book", "tag"], name="uq_booktag")
        ]


class Label(models.Model):
    """Polymorphic owner without an index on (content_type, object_id):
    doctor bait."""

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey()
    name = models.CharField(max_length=50)


class LegacyRow(models.Model):
    """Soft-delete style column + a boolean stored as text: doctor bait."""

    is_active = models.CharField(max_length=6, default="true")
    deleted_at = models.DateTimeField(null=True, blank=True)
