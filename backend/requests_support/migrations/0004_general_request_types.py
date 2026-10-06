from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("requests_support", "0003_chat_attachments"),
    ]

    operations = [
        migrations.AlterField(
            model_name="supportticket",
            name="category",
            field=models.CharField(
                choices=[
                    ("CAMERA", "Camera / CCTV"),
                    ("NVR", "NVR / Recording"),
                    ("NETWORK", "Network / PoE"),
                    ("HARDWARE", "Hardware / Power"),
                    ("SERVER", "Server / Infrastructure"),
                    ("INFRASTRUCTURE", "Infrastructure"),
                    ("ACCESS", "Access / Login"),
                    ("MODULE_ACCESS", "Module Access"),
                    ("VIDEO_EVIDENCE", "Video / Evidence"),
                    ("REPORT", "Report / Data Extract"),
                    ("TRAINING", "Training / How-to"),
                    ("OPS_POLICY", "Ops / Admin / Policy"),
                    ("BACKEND", "Backend / API"),
                    ("FRONTEND", "UI / Frontend"),
                    ("AI_ML", "AI / ML"),
                    ("API", "API"),
                    ("DATABASE", "Database"),
                    ("BUG", "Bug / Error"),
                    ("FEATURE", "Feature Request"),
                    ("GENERAL", "General Request"),
                    ("OTHER", "Other"),
                ],
                db_index=True,
                default="OTHER",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="supportticket",
            name="suggested_category",
            field=models.CharField(
                choices=[
                    ("CAMERA", "Camera / CCTV"),
                    ("NVR", "NVR / Recording"),
                    ("NETWORK", "Network / PoE"),
                    ("HARDWARE", "Hardware / Power"),
                    ("SERVER", "Server / Infrastructure"),
                    ("INFRASTRUCTURE", "Infrastructure"),
                    ("ACCESS", "Access / Login"),
                    ("MODULE_ACCESS", "Module Access"),
                    ("VIDEO_EVIDENCE", "Video / Evidence"),
                    ("REPORT", "Report / Data Extract"),
                    ("TRAINING", "Training / How-to"),
                    ("OPS_POLICY", "Ops / Admin / Policy"),
                    ("BACKEND", "Backend / API"),
                    ("FRONTEND", "UI / Frontend"),
                    ("AI_ML", "AI / ML"),
                    ("API", "API"),
                    ("DATABASE", "Database"),
                    ("BUG", "Bug / Error"),
                    ("FEATURE", "Feature Request"),
                    ("GENERAL", "General Request"),
                    ("OTHER", "Other"),
                ],
                default="OTHER",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="supportticket",
            name="department",
            field=models.CharField(
                choices=[
                    ("IT", "IT"),
                    ("DEVELOPER", "Developer"),
                    ("SUPPORT", "Support"),
                    ("OPERATIONS", "Operations"),
                    ("ADMIN", "Admin"),
                    ("UNASSIGNED", "Unassigned"),
                ],
                db_index=True,
                default="UNASSIGNED",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="supportticket",
            name="suggested_department",
            field=models.CharField(
                choices=[
                    ("IT", "IT"),
                    ("DEVELOPER", "Developer"),
                    ("SUPPORT", "Support"),
                    ("OPERATIONS", "Operations"),
                    ("ADMIN", "Admin"),
                    ("UNASSIGNED", "Unassigned"),
                ],
                default="UNASSIGNED",
                max_length=16,
            ),
        ),
    ]
