from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from .models import ChangesetWrapper, FingerprintWrapper, EventLabel, QueueItem
from .models import QueueItemAdmin, ChangesetWrapperAdmin

"""
Models "registered" below will appear in the admin web interface. You can also
register models using the @admin.register decorator
"""
##Models below have been registered using the decorator and don't need to be here
#admin.site.register(EventLabel, SimpleHistoryAdmin)
#admin.site.register(QueueItem, QueueItemAdmin)
#admin.site.register(ChangesetWrapper, ChangesetWrapperAdmin)
#admin.site.register(FingerprintWrapper, SimpleHistoryAdmin)

admin.site.site_header = "DeltaSherlock Database Admin"
