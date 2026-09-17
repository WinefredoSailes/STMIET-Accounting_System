import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.dev'

import django
django.setup()

from apps.foundation.models import UserProfile
profiles = UserProfile.objects.values('user__username', 'approval_role')
for p in profiles:
    print(f"User: {p['user__username']}, Role: {p['approval_role']}")