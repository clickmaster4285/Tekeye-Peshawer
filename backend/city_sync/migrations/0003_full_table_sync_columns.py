# Add city_sync columns on every business table (full-table sync).

from django.db import migrations


def forwards(apps, schema_editor):
    # Import runtime helpers (not historical models) — alters live tables.
    from city_sync.full_registry import ensure_all_db_sync_columns

    ensure_all_db_sync_columns()


def backwards(apps, schema_editor):
    # Non-destructive: leave columns in place.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("city_sync", "0002_phases_5_to_10"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
