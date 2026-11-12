# Generated migration for adding stock_type field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stock_data', '0003_add_nepse_index_model'),
    ]

    operations = [
        migrations.AddField(
            model_name='stock',
            name='stock_type',
            field=models.CharField(
                choices=[
                    ('stock', 'Stock'),
                    ('mutual_fund', 'Mutual Fund'),
                    ('debenture', 'Debenture'),
                    ('promoter_share', 'Promoter Share'),
                    ('preferred_stock', 'Preferred Stock'),
                ],
                db_index=True,
                default='stock',
                help_text='Type of security: stock, mutual_fund, debenture, etc.',
                max_length=20,
            ),
        ),
        migrations.AddIndex(
            model_name='stock',
            index=models.Index(fields=['stock_type'], name='stock_data__stock_t_c70f9b_idx'),
        ),
        migrations.AddIndex(
            model_name='stock',
            index=models.Index(fields=['stock_type', 'symbol'], name='stock_data__stock_t_4a1d2e_idx'),
        ),
    ]
