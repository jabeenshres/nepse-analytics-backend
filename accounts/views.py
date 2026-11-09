from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
import json

from .access_config import allowed_features
from .serializers import UserRegistrationSerializer, CustomTokenObtainPairSerializer
from .permissions import IsAdmin, HasFeatureAccess


User = get_user_model()

VALID_USER_ROLES = ['manager', 'user']


class RegisterUserView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)

        if serializer.is_valid():
            serializer.save()
            return Response(
                {"message": "User registered successfully"},
                status=status.HTTP_201_CREATED
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer


class MeView(APIView):
    """
    Return the caller's identity and the features their role grants.

    The frontend uses this to build the sidebar and to guard pages, so access rules
    live in one place (accounts/access_config.py) instead of being duplicated in JSX.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        return Response({
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'role': user.role,
            'is_superuser': user.is_superuser,
            'features': sorted(allowed_features(user)),
        }, status=status.HTTP_200_OK)


class UserListView(APIView):
    required_features = ('users',)
    permission_classes = [HasFeatureAccess]

    def get(self, request):
        users = User.objects.all().values('id', 'username', 'email', 'role')
        return Response(users, status=status.HTTP_200_OK)

    def put(self, request):
        try:
            request_data = json.loads(request.body)
            user_id = request_data.get('id')
            new_role = request_data.get('role')

            if not user_id or not new_role:
                return Response(
                    {"error": "User ID and role are required."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            user = get_object_or_404(User, id=user_id)

            if new_role not in VALID_USER_ROLES:
                return Response(
                    {
                        "error": f"Invalid role. Valid roles are: {', '.join(VALID_USER_ROLES)}."
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            user.role = new_role
            user.save()

            return Response(
                {"message": f"Role updated to '{new_role}' for user '{user.username}'."},
                status=status.HTTP_200_OK
            )

        except json.JSONDecodeError:
            return Response(
                {"error": "Invalid JSON body"},
                status=status.HTTP_400_BAD_REQUEST
            )
