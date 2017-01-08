from deltasherlock_server.models import QueueItem, EventLabel
from rest_framework import serializers


class QueueItemSerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = QueueItem
        fields = ('url', 'id', 'status', 'last_updated',
                  'submission_time', 'result_labels')


class EventLabelSerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = EventLabel
        fields = ('url', 'name')
