from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

User = get_user_model()

@receiver(post_save, sender=User)
def assign_admin_role(sender, instance, created, **kwargs):
    # Check if the user is a superuser and was just created
    if created and instance.is_superuser:
        # Assign the admin role to the newly created superuser
        instance.role = User.ADMIN
        instance.save()
