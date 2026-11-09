from django.contrib.auth.models import AbstractUser
from django.db import models

from .access_config import FEATURES


class User(AbstractUser):
    USER = 'user'
    ADMIN = 'admin'
    MANAGER = 'manager'
    ROLE_CHOICES = [
        (USER, 'User'),
        (ADMIN, 'Admin'),
        (MANAGER, 'Manager'),
    ]

    role = models.CharField(
        max_length=10,
        choices=ROLE_CHOICES,
        default=USER
    )

    def __str__(self):
        return self.username


class RoleFeatureAccess(models.Model):
    """
    Editable role -> feature matrix.

    One row per (role, feature); tick ``allowed`` in the admin changelist to grant
    or revoke a sidebar destination for that role. ``accounts/access_config.py``
    reads this table on every permission check, falling back to its code defaults
    only when the table is empty (fresh databases and tests).
    """

    role = models.CharField(max_length=10, choices=User.ROLE_CHOICES)
    feature = models.CharField(
        max_length=50,
        choices=[(key, meta['label']) for key, meta in FEATURES.items()],
        help_text='Sidebar destination key',
    )
    allowed = models.BooleanField(
        default=True,
        help_text='Untick to hide this destination from the role.',
    )

    class Meta:
        verbose_name = 'Role feature access'
        verbose_name_plural = 'Role feature access'
        ordering = ['role', 'feature']
        unique_together = [['role', 'feature']]
        indexes = [models.Index(fields=['role', 'allowed'])]

    def __str__(self):
        return f"{self.role} / {self.feature}: {'allowed' if self.allowed else 'denied'}"
