from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from .serializers import UserRegistrationSerializer, CustomTokenObtainPairSerializer
import json
from accounts.permissions import IsAdmin


User = get_user_model()

# User Registration View
class RegisterUserView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        # Deserialize input data
        serializer = UserRegistrationSerializer(data=request.data)
        
        # Check if the serializer is valid
        if serializer.is_valid():
            user = serializer.save()  # Save the user
            return Response({"message": "User registered successfully"}, status=status.HTTP_201_CREATED)
        
        # If serializer is not valid, return error
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# Custom Token Obtain Pair View (JWT)
class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

# User List and Update Role View
class UserListView(APIView):
    permission_classes = [IsAdmin]  

    def get(self, request):
        # List all users with username, email, and role
        users = User.objects.all().values('id', 'username', 'email', 'role')
        return Response(users, status=status.HTTP_200_OK)

    def put(self, request):
    # Update user role
        try:
            data = json.loads(request.body)
            user_id = data.get('id')
            new_role = data.get('role')

            # Validate input
            if not user_id or not new_role:
                return Response({"error": "User ID and role are required."}, status=status.HTTP_400_BAD_REQUEST)

            # Check if the user exists
            user = get_object_or_404(User, id=user_id)

            # Restrict roles to 'manager' or 'user'
            valid_roles = ['manager', 'user']
            if new_role not in valid_roles:
                return Response({"error": f"Invalid role. Valid roles are: {', '.join(valid_roles)}."}, status=status.HTTP_400_BAD_REQUEST)

            # Update user role and save
            user.role = new_role
            user.save()

            return Response({"message": f"Role updated to '{new_role}' for user '{user.username}'."}, status=status.HTTP_200_OK)

        except json.JSONDecodeError:
            return Response({"error": "Invalid JSON body"}, status=status.HTTP_400_BAD_REQUEST)
