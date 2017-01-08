from django.contrib import admin
from .models import ChangesetWrapper, FingerprintWrapper, EventLabel, QueueItem

"""
Models "registered" below will appear in the admin web interface
"""
admin.site.register(EventLabel)
admin.site.register(QueueItem)
admin.site.register(ChangesetWrapper)
admin.site.register(FingerprintWrapper)
