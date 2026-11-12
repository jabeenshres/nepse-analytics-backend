"""
Seed the editable role -> feature matrix with the values that were previously
hardcoded in accounts/access_config.py.

Deliberately hardcodes the defaults instead of importing ROLE_ACCESS, so this
migration keeps producing the same data even if the code config changes later.
"""
from django.db import migrations


FEATURES = [
    'dashboard',
    'sharelist',
    'top_stocks',
    'indices',
    'screener',
    'broker_holdings',
    'download',
    'users',
    'about',
]

DEFAULT_MATRIX = {
    'admin': set(FEATURES),
    'manager': {
        'dashboard',
        'sharelist',
        'top_stocks',
        'indices',
        'screener',
        'broker_holdings',
        'download',
        'about',
    },
    'user': {
        'dashboard',
        'sharelist',
        'top_stocks',
        'indices',
        'screener',
        'broker_holdings',
        'about',
    },
}


def seed_matrix(apps, schema_editor):
    RoleFeatureAccess = apps.get_model('accounts', 'RoleFeatureAccess')
    RoleFeatureAccess.objects.all().delete()

    entries = [
        RoleFeatureAccess(
            role=role,
            feature=feature,
            allowed=feature in allowed,
        )
        for role, allowed in DEFAULT_MATRIX.items()
        for feature in FEATURES
    ]
    RoleFeatureAccess.objects.bulk_create(entries)


def unseed_matrix(apps, schema_editor):
    RoleFeatureAccess = apps.get_model('accounts', 'RoleFeatureAccess')
    RoleFeatureAccess.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_rolefeatureaccess_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_matrix, unseed_matrix),
    ]
