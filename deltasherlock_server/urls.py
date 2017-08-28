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
router.register(r'changeset', views.ChangesetWrapperViewSet)
router.register(r'swarm/member', views.SwarmMemberViewSet)
router.register(r'swarm/log', views.SwarmMemberLogViewSet)
urlpatterns = router.urls

# We then use custom URL patterns to route the "more complex" items
urlpatterns += [
    url(r'^$', views.api_root),
    url(r'^fingerprint/submit/$', views.FingerprintSubmit.as_view(),
        name="fingerprint-submit"),
    url(r'^fingerprint/rebuild/$', views.RebuildFingerprints.as_view(),
        name="fingerprint-rebuild"),
    url(r'^swarm/changeset/$', views.SwarmChangesetSubmit.as_view(),
        name="swarm-changeset"),
    url(r'^dbadmin/', admin.site.urls, name="dbadmin"),
]

urlpatterns = format_suffix_patterns(urlpatterns)
