from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import SupportTicket, TicketComment


def _emit():
    try:
        from realtime.sio_app import emit_invalidate

        emit_invalidate(["support"], throttle_sec=0.3)
    except Exception:
        pass


@receiver(post_save, sender=SupportTicket)
def ticket_saved(sender, **kwargs):  # noqa: ARG001
    _emit()


@receiver(post_delete, sender=SupportTicket)
def ticket_deleted(sender, **kwargs):  # noqa: ARG001
    _emit()


@receiver(post_save, sender=TicketComment)
def comment_saved(sender, **kwargs):  # noqa: ARG001
    _emit()
