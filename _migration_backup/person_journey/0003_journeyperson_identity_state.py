"""Restore identity_state on JourneyPerson.

The live table already has this NOT NULL column (and its index) from an older
schema. Django was omitting it on insert, so new people failed with
NotNullViolation. State is updated either way; the SQL only adds the column
when it is missing and sets a default so inserts cannot send NULL.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("person_journey", "0002_rename_person_journey_indexes"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="journeyperson",
                    name="identity_state",
                    field=models.CharField(
                        choices=[
                            ("new", "New"),
                            ("tracking", "Tracking"),
                            ("continuous", "Continuous"),
                        ],
                        db_index=True,
                        default="new",
                        max_length=24,
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE person_journey_journeyperson
                        ADD COLUMN IF NOT EXISTS identity_state varchar(24);
                        UPDATE person_journey_journeyperson
                        SET identity_state = 'new'
                        WHERE identity_state IS NULL;
                        ALTER TABLE person_journey_journeyperson
                        ALTER COLUMN identity_state SET DEFAULT 'new';
                        ALTER TABLE person_journey_journeyperson
                        ALTER COLUMN identity_state SET NOT NULL;
                        CREATE INDEX IF NOT EXISTS person_journey_journeyperson_identity_state_7bb43e09
                        ON person_journey_journeyperson (identity_state);
                        CREATE INDEX IF NOT EXISTS person_journey_journeyperson_identity_state_7bb43e09_like
                        ON person_journey_journeyperson (identity_state varchar_pattern_ops);
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
