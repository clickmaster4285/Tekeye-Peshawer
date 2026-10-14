# Align legacy recognition_facesample schema with FaceSample model.
# 0003_face_samples was recorded as applied while an older table shape remained
# (candidate_staff_id, no staff_id / suggested_staff_id / model_name / quality).

from django.db import migrations


FORWARD_SQL = """
ALTER TABLE recognition_facesample
    ADD COLUMN IF NOT EXISTS staff_id bigint NULL;
ALTER TABLE recognition_facesample
    ADD COLUMN IF NOT EXISTS suggested_staff_id bigint NULL;
ALTER TABLE recognition_facesample
    ADD COLUMN IF NOT EXISTS model_name varchar(50) NOT NULL DEFAULT '';
ALTER TABLE recognition_facesample
    ADD COLUMN IF NOT EXISTS quality double precision NOT NULL DEFAULT 0.0;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'recognition_facesample' AND column_name = 'candidate_staff_id'
    ) THEN
        UPDATE recognition_facesample
        SET suggested_staff_id = candidate_staff_id
        WHERE suggested_staff_id IS NULL AND candidate_staff_id IS NOT NULL;

        UPDATE recognition_facesample
        SET staff_id = candidate_staff_id
        WHERE staff_id IS NULL
          AND candidate_staff_id IS NOT NULL
          AND status = 'approved';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'recognition_facesample_staff_id_fk'
    ) THEN
        ALTER TABLE recognition_facesample
            ADD CONSTRAINT recognition_facesample_staff_id_fk
            FOREIGN KEY (staff_id) REFERENCES users_staff(id)
            ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'recognition_facesample_suggested_staff_id_fk'
    ) THEN
        ALTER TABLE recognition_facesample
            ADD CONSTRAINT recognition_facesample_suggested_staff_id_fk
            FOREIGN KEY (suggested_staff_id) REFERENCES users_staff(id)
            ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS recognition_facesample_staff_id_idx
    ON recognition_facesample (staff_id);
CREATE INDEX IF NOT EXISTS recognition_facesample_suggested_staff_id_idx
    ON recognition_facesample (suggested_staff_id);
"""


REVERSE_SQL = """
ALTER TABLE recognition_facesample DROP CONSTRAINT IF EXISTS recognition_facesample_staff_id_fk;
ALTER TABLE recognition_facesample DROP CONSTRAINT IF EXISTS recognition_facesample_suggested_staff_id_fk;
DROP INDEX IF EXISTS recognition_facesample_staff_id_idx;
DROP INDEX IF EXISTS recognition_facesample_suggested_staff_id_idx;
ALTER TABLE recognition_facesample DROP COLUMN IF EXISTS staff_id;
ALTER TABLE recognition_facesample DROP COLUMN IF EXISTS suggested_staff_id;
ALTER TABLE recognition_facesample DROP COLUMN IF EXISTS model_name;
ALTER TABLE recognition_facesample DROP COLUMN IF EXISTS quality;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("recognition", "0003_face_samples"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # Django state already includes these fields from 0003_face_samples.
            state_operations=[],
            database_operations=[
                migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
            ],
        ),
    ]
