from django.contrib import admin
from django.contrib.auth import get_user_model

from .models import RoleFeatureAccess

User = get_user_model()


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'email', 'role', 'is_staff', 'is_superuser')
    search_fields = ('username', 'email')
    list_filter = ('role', 'is_staff', 'is_superuser')


@admin.register(RoleFeatureAccess)
class RoleFeatureAccessAdmin(admin.ModelAdmin):
    """
    Editable access matrix.

    Filter by role, tick/untick ``allowed`` directly in the list and press Save.
    Changes take effect on the next request; the sidebar and the API both read this
    table through accounts/access_config.py.
    """

    list_display = ('role', 'feature', 'allowed')
    list_editable = ('allowed',)
    list_filter = ('role', 'allowed')
    search_fields = ('feature',)
    ordering = ('role', 'feature')
    list_per_page = 50
    actions = ('allow_selected', 'deny_selected')

    @admin.action(description='Allow selected features')
    def allow_selected(self, request, queryset):
        updated = queryset.update(allowed=True)
        self.message_user(request, f'{updated} entries allowed.')

    @admin.action(description='Deny selected features')
    def deny_selected(self, request, queryset):
        updated = queryset.update(allowed=False)
        self.message_user(request, f'{updated} entries denied.')
