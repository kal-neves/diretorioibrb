import os
import sys

from django.core.management import execute_from_command_line


if __name__ == "__main__":
    default_settings = "config.settings.production" if os.environ.get("VERCEL") == "1" else "config.settings.development"
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", default_settings)
    execute_from_command_line(sys.argv)
