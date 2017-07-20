from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from .models import ChangesetWrapper, FingerprintWrapper, EventLabel, QueueItem

"""
Models "registered" below will appear in the admin web interface
"""
admin.site.register(EventLabel, SimpleHistoryAdmin)
admin.site.register(QueueItem, SimpleHistoryAdmin)
admin.site.register(ChangesetWrapper, SimpleHistoryAdmin)
admin.site.register(FingerprintWrapper, SimpleHistoryAdmin)
