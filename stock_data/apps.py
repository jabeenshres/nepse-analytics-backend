from django.apps import AppConfig
from django.db.backends.signals import connection_created


class StockDataConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'stock_data'

    def ready(self):
        connection_created.connect(
            _set_sqlite_pragmas,
            dispatch_uid='stock_data.set_sqlite_pragmas',
        )


def _set_sqlite_pragmas(sender, connection, **kwargs):
    """Use WAL on SQLite so web reads are not blocked by scrape writes.

    No-op on PostgreSQL. WAL is persistent per database file; synchronous=NORMAL
    is the recommended pairing. cache_size is negative, i.e. KiB (-64000 = 64 MB).
    """
    if connection.vendor != 'sqlite':
        return
    with connection.cursor() as cursor:
        cursor.execute('PRAGMA journal_mode=WAL;')
        cursor.execute('PRAGMA synchronous=NORMAL;')
        cursor.execute('PRAGMA cache_size=-64000;')
