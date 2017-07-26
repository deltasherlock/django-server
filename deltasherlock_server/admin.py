from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from .models import ChangesetWrapper, FingerprintWrapper, EventLabel, QueueItem, QueueItemAdmin, ChangesetWrapperAdmin

"""
Models "registered" below will appear in the admin web interface
"""
admin.site.register(EventLabel, SimpleHistoryAdmin)
admin.site.register(QueueItem, QueueItemAdmin)
admin.site.register(ChangesetWrapper, ChangesetWrapperAdmin)
admin.site.register(FingerprintWrapper, SimpleHistoryAdmin)

admin.site.site_header = "DeltaSherlock Database Admin"
