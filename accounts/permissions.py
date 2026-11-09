from rest_framework.permissions import BasePermission, SAFE_METHODS
from django.contrib.auth import get_user_model

from .access_config import (
    VIEW_FEATURES,
    VIEW_WRITE_FEATURES,
    has_feature,
)

User = get_user_model()


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and
            user.is_authenticated and
            (user.is_superuser or user.role == User.ADMIN)
        )


class IsAdminOrManager(BasePermission):
    """
    Grants access if the user's role is either 'admin' or 'manager'.
    """
    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and
            user.is_authenticated and
            (user.is_superuser or user.role in [User.ADMIN, User.MANAGER])
        )


class HasFeatureAccess(BasePermission):
    """
    Default permission for the whole API.

    - Anonymous users are rejected.
    - A view with no ``required_features`` is open to any authenticated user.
    - A view with ``required_features`` needs at least one matching feature.
    - Unsafe methods (POST/PUT/PATCH/DELETE) can be narrowed further with
      ``write_features``, so read-only endpoints stay writable only by ingest roles.
    - Superusers bypass every feature check.

    ``required_features`` / ``write_features`` accept a string or an iterable.
    """

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False

        if getattr(user, 'is_superuser', False):
            return True

        view_name = view.__class__.__name__

        # View-level declarations win over the central config.
        required = getattr(view, 'required_features', None)
        if required is None:
            required = VIEW_FEATURES.get(view_name)

        write_required = getattr(view, 'write_features', None)
        if write_required is None:
            write_required = VIEW_WRITE_FEATURES.get(view_name)

        if request.method not in SAFE_METHODS and write_required is not None:
            required = write_required

        if not required:
            return True

        if isinstance(required, str):
            required = (required,)

        return any(has_feature(user, feature) for feature in required)
