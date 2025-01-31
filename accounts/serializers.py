from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken

class UserRegistrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = get_user_model()
        fields = ['username', 'password', 'email']

    def create(self, validated_data):
        # Create the user
        user = super().create(validated_data)
        user.set_password(validated_data['password'])
        
        user.role = 'user'  # Default role for normal users
        
        user.save()
        return user


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        user = self.user
        data['role'] = user.role  # Add role to token
        data['username'] = user.username
        return data