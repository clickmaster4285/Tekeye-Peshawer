# Legacy FaceSample columns (camera_name, review_note) are NOT NULL but are
# no longer written by the current model — relax them so inserts succeed.

from django.db import migrations


FORWARD_SQL = """
ALTER TABLE recognition_facesample
    ALTER COLUMN camera_name DROP NOT NULL;
ALTER TABLE recognition_facesample
    ALTER COLUMN camera_name SET DEFAULT '';

ALTER TABLE recognition_facesample
    ALTER COLUMN review_note DROP NOT NULL;
ALTER TABLE recognition_facesample
    ALTER COLUMN review_note SET DEFAULT '';

UPDATE recognition_facesample SET camera_name = '' WHERE camera_name IS NULL;
UPDATE recognition_facesample SET review_note = '' WHERE review_note IS NULL;
"""


REVERSE_SQL = """
ALTER TABLE recognition_facesample ALTER COLUMN camera_name DROP DEFAULT;
ALTER TABLE recognition_facesample ALTER COLUMN review_note DROP DEFAULT;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("recognition", "0004_align_facesample_columns"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
            ],
        ),
    ]
