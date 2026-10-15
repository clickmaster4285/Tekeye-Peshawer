from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0026_merge_20260919_1408"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="location",
            field=models.CharField(
                blank=True,
                choices=[
                    ("PESHAWAR", "Peshawar (Head Office)"),
                    ("ABBOTTABAD", "Abbottabad"),
                    ("DI_KHAN", "DI Khan"),
                    ("DDK", "DDK"),
                    ("THAKOT", "Thakot"),
                    ("HAYATABAD", "Hayatabad"),
                    ("MARDAN", "Mardan"),
                    ("NOWSHERA", "Nowshera"),
                    ("KOHAT", "Kohat"),
                    ("SWH_RATTA_KULACHI", "SWH Ratta Kulachi"),
                ],
                default="",
                max_length=20,
            ),
        ),
    ]
