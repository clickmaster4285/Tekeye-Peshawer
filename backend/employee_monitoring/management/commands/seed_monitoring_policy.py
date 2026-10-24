"""Create (or activate) a starter monitoring policy so the app has something to show.

Edit the text to match the organization's approved policy before using in production.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from employee_monitoring.models import MonitoringPolicy
from employee_monitoring.services import deployment_id, retention_days


class Command(BaseCommand):
    help = "Create and activate a default employee-monitoring policy."

    def add_arguments(self, parser):
        parser.add_argument("--policy-version", default="2026-01", help="Policy version string.")

    @transaction.atomic
    def handle(self, *args, **options):
        version = options["policy_version"]
        ret = retention_days() or None
        categories = [
            {
                "key": "work_session_location",
                "label": "Work-session location",
                "description": "Your GPS location while an authorized work session is active, for check-ins and duty verification.",
                "collected": True,
                "retention_days": ret,
                "measurement": "measured",
            },
            {
                "key": "work_session_status",
                "label": "Work-session status",
                "description": "When you start and end a work session, and app foreground/locked time on your work phone.",
                "collected": True,
                "retention_days": ret,
                "measurement": "measured",
            },
            {
                "key": "attendance",
                "label": "Attendance",
                "description": "Your check-in and check-out times.",
                "collected": True,
                "retention_days": ret,
                "measurement": "measured",
            },
            {
                "key": "call_metadata",
                "label": "Work call metadata",
                "description": "Direction, masked number, time and duration of work calls, from the approved telephony system only — never read from your phone.",
                "collected": True,
                "retention_days": ret,
                "measurement": "measured",
            },
            {
                "key": "call_recording",
                "label": "Work call recordings",
                "description": "Recordings of work calls captured by the approved company telephony system, where that system records them. The app does not record calls.",
                "collected": True,
                "retention_days": ret,
                "measurement": "measured",
            },
        ]
        MonitoringPolicy.objects.filter(is_active=True).update(is_active=False)
        policy, created = MonitoringPolicy.objects.update_or_create(
            version=version,
            defaults={
                "effective_at": timezone.now(),
                "summary": (
                    "During authorized work sessions, CIIS collects the data listed below to protect staff "
                    "on duty and keep accurate work records. Records are visible to your supervisors, HR and "
                    "authorized administrators for this deployment. Call recordings come only from the approved "
                    "company telephony system; the app never records calls or reads your call log from the phone."
                ),
                "work_hours": "During authorized work sessions only.",
                "contact": "Contact your HR or IT administrator for questions, data requests, or withdrawal.",
                "categories": categories,
                "is_active": True,
            },
        )
        self.stdout.write(self.style.SUCCESS(
            f"{'Created' if created else 'Updated'} and activated policy {version} for {deployment_id()}."
        ))
