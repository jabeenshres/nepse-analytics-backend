from datetime import datetime, timezone

from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import AccessToken


User = get_user_model()


class UserRegistrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['username', 'password', 'email']

    def create(self, validated_data):
        user = super().create(validated_data)
        user.set_password(validated_data['password'])
        user.role = User.USER
        user.save()
        return user


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        user = self.user
        data['role'] = user.role
        data['username'] = user.username
        data['is_superuser'] = user.is_superuser

        # Lets the frontend refresh proactively instead of waiting for a 401.
        try:
            expires_at = AccessToken(data['access'])['exp']
            data['access_expires_at'] = datetime.fromtimestamp(
                expires_at, tz=timezone.utc
            ).isoformat()
        except Exception:
            data['access_expires_at'] = None

        return data
