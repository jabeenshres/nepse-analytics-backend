from django.urls import path
from . import views
from .views import RegisterUserView


urlpatterns = [
    path('register/', RegisterUserView.as_view(), name='register_user'),
    path('token/', views.CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
]
