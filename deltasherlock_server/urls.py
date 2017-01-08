"""
The central "URL dispatcher" that controls routing and flow of user interactions.
See https://docs.djangoproject.com/en/1.10/topics/http/urls/
"""

from django.conf.urls import url
from django.contrib import admin
from rest_framework.urlpatterns import format_suffix_patterns
from rest_framework import routers
from . import views

# We use DRF's routers to automatically generate routes for "simple" objects
# that use generic ViewSets
router = routers.SimpleRouter()
router.register(r'queue', views.QueueItemViewSet)
router.register(r'label', views.EventLabelViewSet)
urlpatterns = router.urls

# We then use custom URL patterns to route the "more complex" items
urlpatterns += [
    url(r'^$', views.api_root),
    url(r'^fingerprint/submit/$', views.FingerprintSubmit.as_view(),
        name="fingerprint-submit"),
    url(r'^fingerprint/rebuild/$', views.RebuildFingerprints.as_view(),
        name="fingerprint-rebuild"),
    url(r'^admin/', admin.site.urls, name="admin"),
]

urlpatterns = format_suffix_patterns(urlpatterns)
