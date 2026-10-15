from django.db import migrations


class Migration(migrations.Migration):
    """
    Join the two users migration branches into one codebase:
    - Peshawar HQ: 0027_support_tickets_and_roles -> 0028_add_abbottabad_ddk_thakot_hayatabad_locations
    - City servers (old Abbottabad code): 0027_add_more_locations -> 0029 -> 0030 -> 0031
    Each database applies only the branch it is missing; both branches only add
    sync columns or alter choices, so they do not conflict.
    """

    dependencies = [
        ("users", "0028_add_abbottabad_ddk_thakot_hayatabad_locations"),
        ("users", "0031_alter_user_location_and_role"),
    ]

    operations = []
