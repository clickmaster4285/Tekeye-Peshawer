"""
WSGI config for config project.

Socket.IO is mounted on the same HTTP port as Django so browsers can use
same-origin /socket.io for realtime invalidations.
"""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.wsgi import get_wsgi_application

django_app = get_wsgi_application()

try:
    from realtime.sio_app import wrap_wsgi

    application = wrap_wsgi(django_app)
except Exception:
    # Fallback if realtime deps missing — API still works without sockets, but every
    # browser then retries /socket.io once a second and loses cache invalidation, so
    # make the cause loud rather than silently degrading.
    import logging

    logging.getLogger(__name__).exception(
        "Socket.IO could not be mounted; realtime updates are disabled. "
        "Install the realtime deps (pip install -r requirements.txt)."
    )
    application = django_app
