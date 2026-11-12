from django.test import TestCase
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model

from .access_config import allowed_features, has_feature
from .models import RoleFeatureAccess


User = get_user_model()


class AccessConfigTests(TestCase):
    def test_role_feature_sets(self):
        manager = self._user('manager')
        user = self._user('user')

        self.assertIn('download', allowed_features(manager))
        self.assertNotIn('users', allowed_features(manager))
        self.assertNotIn('download', allowed_features(user))
        self.assertIn('dashboard', allowed_features(user))

    def test_admin_gets_every_feature(self):
        admin = self._user('admin')
        self.assertIn('users', allowed_features(admin))
        self.assertIn('download', allowed_features(admin))

    def test_superuser_bypasses_role(self):
        superuser = User.objects.create_superuser(
            username='root', password='pass1234', email='root@example.com'
        )
        superuser.role = User.USER
        superuser.save(update_fields=['role'])

        self.assertIn('users', allowed_features(superuser))
        self.assertTrue(has_feature(superuser, 'download'))

    def test_anonymous_has_no_features(self):
        self.assertEqual(allowed_features(None), set())

    def _user(self, role):
        return User.objects.create_user(
            username=f'{role}_user', password='pass1234', role=role
        )


class ApiPermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_anonymous_is_rejected_on_read(self):
        response = self.client.get('/api/stock-data/')
        self.assertIn(response.status_code, (401, 403))

    def test_anonymous_is_rejected_on_users(self):
        response = self.client.get('/api/accounts/users/')
        self.assertIn(response.status_code, (401, 403))

    def test_user_can_read_stock_data(self):
        self._auth('user')
        response = self.client.get('/api/stock-data/')
        self.assertEqual(response.status_code, 200)

    def test_user_cannot_list_users(self):
        self._auth('user')
        response = self.client.get('/api/accounts/users/')
        self.assertEqual(response.status_code, 403)

    def test_manager_cannot_list_users(self):
        self._auth('manager')
        response = self.client.get('/api/accounts/users/')
        self.assertEqual(response.status_code, 403)

    def test_admin_can_list_users(self):
        self._auth('admin')
        response = self.client.get('/api/accounts/users/')
        self.assertEqual(response.status_code, 200)

    def test_superuser_can_list_users(self):
        self.client.force_authenticate(
            user=User.objects.create_superuser(
                username='root', password='pass1234', email='root@example.com'
            )
        )
        response = self.client.get('/api/accounts/users/')
        self.assertEqual(response.status_code, 200)

    def _auth(self, role):
        user = User.objects.create_user(
            username=f'{role}_api', password='pass1234', role=role
        )
        self.client.force_authenticate(user=user)
        return user


class MeViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_me_returns_features_for_role(self):
        user = User.objects.create_user(
            username='me_user', password='pass1234', role=User.MANAGER
        )
        self.client.force_authenticate(user=user)

        response = self.client.get('/api/accounts/me/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['role'], 'manager')
        self.assertIn('download', response.data['features'])
        self.assertNotIn('users', response.data['features'])

    def test_me_requires_authentication(self):
        response = self.client.get('/api/accounts/me/')
        self.assertIn(response.status_code, (401, 403))


class TokenTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='token_user', password='pass1234', role=User.USER
        )

    def test_login_returns_role_expiry_and_superuser_flag(self):
        response = self.client.post('/api/accounts/token/', {
            'username': 'token_user',
            'password': 'pass1234',
        }, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['role'], 'user')
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertTrue(response.data['access_expires_at'])
        self.assertFalse(response.data['is_superuser'])

    def test_refresh_route_exists(self):
        login = self.client.post('/api/accounts/token/', {
            'username': 'token_user',
            'password': 'pass1234',
        }, format='json')

        response = self.client.post('/api/token/refresh/', {
            'refresh': login.data['refresh'],
        }, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.data)


class RoleFeatureMatrixTests(TestCase):
    """
    The matrix is now DB-backed so it can be edited in Django admin. The seeded rows
    must reproduce the old defaults, and toggling a row must change access.
    """

    def _user(self, role):
        return User.objects.create_user(
            username=f'matrix_{role}', password='pass1234', role=role
        )

    def test_seed_matches_previous_defaults(self):
        manager = self._user('manager')
        user = self._user('user')

        self.assertIn('download', allowed_features(manager))
        self.assertIn('users', allowed_features(self._user('admin')))
        self.assertNotIn('download', allowed_features(user))
        self.assertIn('dashboard', allowed_features(user))

    def test_revoking_a_row_removes_the_feature(self):
        user = self._user('user')
        self.assertIn('screener', allowed_features(user))

        RoleFeatureAccess.objects.filter(role='user', feature='screener').update(
            allowed=False
        )

        self.assertNotIn('screener', allowed_features(user))

    def test_granting_a_row_adds_the_feature(self):
        manager = self._user('manager')
        self.assertNotIn('users', allowed_features(manager))

        RoleFeatureAccess.objects.filter(role='manager', feature='users').update(
            allowed=True
        )

        self.assertIn('users', allowed_features(manager))

    def test_empty_matrix_falls_back_to_code_defaults(self):
        RoleFeatureAccess.objects.all().delete()

        features = allowed_features(self._user('user'))

        self.assertIn('dashboard', features)
        self.assertIn('sharelist', features)

    def test_every_role_feature_pair_is_seeded(self):
        roles = ['admin', 'manager', 'user']
        features = list(RoleFeatureAccess.objects.values_list('feature', flat=True))

        self.assertEqual(
            RoleFeatureAccess.objects.count(), len(roles) * len(set(features))
        )
