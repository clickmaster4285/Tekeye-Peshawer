from django.db import migrations, models


def copy_purpose_to_purposes(apps, schema_editor):
    Camera = apps.get_model("cameras", "Camera")
    for cam in Camera.objects.all().iterator():
        purpose = (cam.purpose or "surveillance").strip().lower() or "surveillance"
        cam.purposes = [purpose]
        cam.save(update_fields=["purposes"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("cameras", "0012_camera_passage_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="camera",
            name="purposes",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="AI purposes enabled on this camera (multiple models allowed).",
            ),
        ),
        migrations.AlterField(
            model_name="camera",
            name="purpose",
            field=models.CharField(
                choices=[
                    ("surveillance", "General Surveillance"),
                    ("object_detection", "Object Detection (YOLO)"),
                    ("face_recognition", "Face Recognition"),
                    ("attendance", "Attendance Check-in"),
                    ("anpr", "ANPR / Vehicle"),
                    ("zone_monitoring", "Zone Access Monitoring"),
                    ("thermal", "Thermal Anomaly"),
                ],
                default="surveillance",
                help_text="Primary AI purpose (first entry of purposes).",
                max_length=32,
            ),
        ),
        migrations.RunPython(copy_purpose_to_purposes, noop_reverse),
    ]
