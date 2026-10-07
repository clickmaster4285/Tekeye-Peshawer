from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0027_support_tickets_and_roles"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="location",
            field=models.CharField(
                blank=True,
                choices=[
                    ("PESHAWAR", "Peshawar (Head Office)"),
                    ("KOHAT", "Kohat"),
                    ("NOWSHERA", "Nowshera"),
                    ("MARDAN", "Mardan"),
                    ("DI_KHAN", "DI Khan"),
                    ("SWH_RATTA_KULACHI", "SWH Ratta Kulachi"),
                    ("ABBOTTABAD", "Abbottabad"),
                    ("DDK", "DDK"),
                    ("THAKOT", "Thakot"),
                    ("HAYATABAD", "Hayatabad"),
                ],
                default="",
                max_length=20,
            ),
        ),
    ]
