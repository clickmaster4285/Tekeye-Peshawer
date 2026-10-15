"""Restore CameraTrack columns the live table already requires.

Inserts were omitting tracklet_id, bboxes, zones, and movement_direction.
Those columns are NOT NULL with no default, so every new camera track failed.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("person_journey", "0003_journeyperson_identity_state"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="cameratrack",
                    name="tracklet_id",
                    field=models.CharField(
                        blank=True,
                        default="",
                        help_text="Stable id for this camera track, C{camera_id}-T{track_id}.",
                        max_length=64,
                    ),
                ),
                migrations.AddField(
                    model_name="cameratrack",
                    name="last_seen_at",
                    field=models.DateTimeField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="cameratrack",
                    name="start_bbox",
                    field=models.JSONField(blank=True, default=list),
                ),
                migrations.AddField(
                    model_name="cameratrack",
                    name="end_bbox",
                    field=models.JSONField(blank=True, default=list),
                ),
                migrations.AddField(
                    model_name="cameratrack",
                    name="trajectory",
                    field=models.JSONField(blank=True, default=list),
                ),
                migrations.AddField(
                    model_name="cameratrack",
                    name="entry_zone",
                    field=models.CharField(blank=True, default="", max_length=64),
                ),
                migrations.AddField(
                    model_name="cameratrack",
                    name="exit_zone",
                    field=models.CharField(blank=True, default="", max_length=64),
                ),
                migrations.AddField(
                    model_name="cameratrack",
                    name="movement_direction",
                    field=models.CharField(blank=True, default="", max_length=32),
                ),
                migrations.AddField(
                    model_name="cameratrack",
                    name="quality",
                    field=models.FloatField(blank=True, null=True),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE person_journey_cameratrack
                            ADD COLUMN IF NOT EXISTS tracklet_id varchar(64),
                            ADD COLUMN IF NOT EXISTS last_seen_at timestamptz,
                            ADD COLUMN IF NOT EXISTS start_bbox jsonb,
                            ADD COLUMN IF NOT EXISTS end_bbox jsonb,
                            ADD COLUMN IF NOT EXISTS trajectory jsonb,
                            ADD COLUMN IF NOT EXISTS entry_zone varchar(64),
                            ADD COLUMN IF NOT EXISTS exit_zone varchar(64),
                            ADD COLUMN IF NOT EXISTS movement_direction varchar(32),
                            ADD COLUMN IF NOT EXISTS quality double precision;

                        UPDATE person_journey_cameratrack
                        SET tracklet_id = COALESCE(NULLIF(tracklet_id, ''), 'C' || camera_id || '-T' || track_id)
                        WHERE tracklet_id IS NULL OR tracklet_id = '';

                        UPDATE person_journey_cameratrack SET start_bbox = '[]'::jsonb WHERE start_bbox IS NULL;
                        UPDATE person_journey_cameratrack SET end_bbox = '[]'::jsonb WHERE end_bbox IS NULL;
                        UPDATE person_journey_cameratrack SET trajectory = '[]'::jsonb WHERE trajectory IS NULL;
                        UPDATE person_journey_cameratrack SET entry_zone = '' WHERE entry_zone IS NULL;
                        UPDATE person_journey_cameratrack SET exit_zone = '' WHERE exit_zone IS NULL;
                        UPDATE person_journey_cameratrack SET movement_direction = '' WHERE movement_direction IS NULL;

                        ALTER TABLE person_journey_cameratrack
                            ALTER COLUMN tracklet_id SET DEFAULT '',
                            ALTER COLUMN tracklet_id SET NOT NULL,
                            ALTER COLUMN start_bbox SET DEFAULT '[]'::jsonb,
                            ALTER COLUMN start_bbox SET NOT NULL,
                            ALTER COLUMN end_bbox SET DEFAULT '[]'::jsonb,
                            ALTER COLUMN end_bbox SET NOT NULL,
                            ALTER COLUMN trajectory SET DEFAULT '[]'::jsonb,
                            ALTER COLUMN trajectory SET NOT NULL,
                            ALTER COLUMN entry_zone SET DEFAULT '',
                            ALTER COLUMN entry_zone SET NOT NULL,
                            ALTER COLUMN exit_zone SET DEFAULT '',
                            ALTER COLUMN exit_zone SET NOT NULL,
                            ALTER COLUMN movement_direction SET DEFAULT '',
                            ALTER COLUMN movement_direction SET NOT NULL;
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
