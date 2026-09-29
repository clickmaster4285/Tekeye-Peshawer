#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run [01/Sep/2026 21:33:17] "POST /api/auth/login/ HTTP/1.1" 400 54
^C^C(venv) root@tekeye-server-peshawar:/var/www/CustomPeshawar/backend# ^C
(venv) root@tekeye-server-peshawar:/var/www/CustomPeshawar/backend# ^C
(venv) root@tekeye-server-peshawar:/var/www/CustomPeshawar/backend# python manage.py runserver 0.0.0.0:8000
Watching for file changes with StatReloader
Performing system checks...

System check identified no issues (0 silenced).
September 01, 2026 - 21:34:23
Django version 5.2.11, using settings 'config.settings'
Starting development server at http://0.0.0.0:8000/
Quit the server with CONTROL-C.

WARNING: This is a development server. Do not use it in a production setting. Use a production WSGI or ASGI server instead.
For more information on production servers see: https://docs.djangoproject.com/en/5.2/howto/deployment/
^C^C(venv) root@tekeye-server-peshawar:/var/www/CustomPeshawar/backend# ^C
(venv) root@tekeye-server-peshawar:/var/www/CustomPeshawar/backend# python manage.py createsuperuser
Username: admin
Email address: admin@gmail.com
Role: admin
Error: Value 'admin' is not a valid choice.
Role: superadmin
Error: Value 'superadmin' is not a valid choice.
Role:istrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
