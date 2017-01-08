"""
The "view" part of the "Model-Template-View" pattern is defined here. Essentially,
these methods are the first to receive each client HTTP request (after the URL
dispatcher). Remember that these views are unreachable unless you route them
within "urls.py"
"""
import os
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.decorators import api_view
from rest_framework import status
from rest_framework import viewsets
from redis import Redis
from rq import Queue
from deltasherlock.server import manager
from deltasherlock.common.fingerprinting import FingerprintingMethod
from deltasherlock_server import models
from deltasherlock_server import serializers


@api_view(['GET'])
def api_root(request, format=None):
    """
    Home page of the API
    """
    return Response({
        'admin': reverse('admin', request=request, format=format),
        'queueitem-list': reverse('queueitem-list', request=request, format=format),
        'eventlabel-list': reverse('eventlabel-list', request=request, format=format),
        'fingerprint-submit': reverse('fingerprint-submit', request=request, format=format),
        'fingerprint-rebuild': reverse('fingerprint-rebuild', request=request, format=format),
    })


class FingerprintSubmit(APIView):
    """
    Submit a fingerprint to the queue
    """

    def post(self, request, format=None):
        # TODO Log all errors!

        # First connect to Redis
        try:
            q = Queue(connection=Redis())
        except:
            return Response("Could not reach Redis", status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Then submit the job to RQ
        rq_job = None
        try:
            django_params = {
                "proj_path": settings.BASE_DIR,
                "settings_module": os.environ.get("DJANGO_SETTINGS_MODULE"),
            }
            rq_job = q.enqueue('deltasherlock.server.worker.process_fingerprint',
                               request.data['fingerprint'],
                               request.data['endpoint_url'],
                               request.data['parameters'],
                               django_params)
        except:
            return Response("Rejected by job queue. Check submission data and try again.", status=status.HTTP_400_BAD_REQUEST)

        # Finally, create a record of the request in the QueueItem database
        queue_id = models.QueueItem().from_request(request=request, rq_id=rq_job.id)

        return Response(queue_id, status=status.HTTP_202_ACCEPTED)


class RebuildFingerprints(APIView):
    """
    Rebuild all fingerprints in the database of a specified type. Must specify
    the following parameters in the URL: parallel = 0 or 1. method = the numeric
    value of the FingerprintingMethod to be used
    """

    def get(self, request, format=None):
        # Get all of the changesets from the database
        changesets = []
        for changeset_wrapper in models.ChangesetWrapper.objects.all():
            changesets.append(changeset_wrapper.unwrap())

        fingerprints = []
        if request.query_params['parallel'] is '1':
            fingerprints = manager.generate_fingerprints_parallel(changesets=changesets,
                                                                  method=FingerprintingMethod(
                                                                      int(request.query_params['method'])),
                                                                  save_path=os.path.abspath(settings.BASE_DIR) + "/deltasherlock_server/static/")
        else:
            fingerprints = manager.generate_fingerprints(changesets=changesets,
                                                         method=FingerprintingMethod(
                                                             int(request.query_params['method'])),
                                                         save_path=os.path.abspath(settings.BASE_DIR) + "/deltasherlock_server/static/")

        # Now delete all old fingerprints
        models.FingerprintWrapper.objects.all().delete()

        # And repopulate the database
        for fingerprint in fingerprints:
            models.FingerprintWrapper().wrap(fingerprint)

        # All done!
        return Response(status=status.HTTP_200_OK)


class QueueItemViewSet(viewsets.ReadOnlyModelViewSet):
    """
    List and get details on all QueueItems in the database
    """
    queryset = models.QueueItem.objects.all()
    serializer_class = serializers.QueueItemSerializer


class EventLabelViewSet(viewsets.ReadOnlyModelViewSet):
    """
    List and get details on all EventLabels in the database
    """
    queryset = models.EventLabel.objects.all()
    serializer_class = serializers.EventLabelSerializer
