from rest_framework.permissions import BasePermission
from django.contrib.auth import get_user_model

User = get_user_model()


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role == User.ADMIN
        )


class IsAdminOrManager(BasePermission):
    """
    Grants access if the user's role is either 'admin' or 'manager'.
    """
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role in [User.ADMIN, User.MANAGER]
        )
