"""Post-sale support: tickets, messages and service levels."""

from django.conf import settings
from django.db import models

from sales.models import Customer, SalesOrder


class SlaPolicy(models.Model):
    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    name = models.CharField(max_length=120, unique=True)
    priority = models.CharField(max_length=16, choices=Priority.choices)
    first_response_hours = models.PositiveSmallIntegerField()
    resolution_hours = models.PositiveSmallIntegerField()


class CannedResponse(models.Model):
    title = models.CharField(max_length=200)
    body = models.TextField()
    tags = models.CharField(max_length=255, blank=True)
    usage_count = models.PositiveIntegerField(default=0)


class Ticket(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        PENDING = "pending", "Pending"
        SOLVED = "solved", "Solved"
        CLOSED = "closed", "Closed"

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="tickets")
    order = models.ForeignKey(
        SalesOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets"
    )
    subject = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    priority = models.CharField(max_length=16, choices=SlaPolicy.Priority.choices)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets",
    )
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)


class TicketMessage(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="ticket_messages"
    )
    body = models.TextField()
    is_internal = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
