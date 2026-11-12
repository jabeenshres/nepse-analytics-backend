from django.urls import path
from . import views
from .views import RegisterUserView, UserListView, MeView


urlpatterns = [
    path('register/', RegisterUserView.as_view(), name='register_user'),
    path('token/', views.CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('me/', MeView.as_view(), name='me'),
    path('users/', UserListView.as_view(), name='list_or_update_user'),
]
