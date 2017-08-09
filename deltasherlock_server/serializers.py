from deltasherlock_server.models import QueueItem, EventLabel, SwarmMemberLog
from rest_framework import serializers


class QueueItemSerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = QueueItem
        fields = ('url', 'id', 'status', 'last_updated', 'submission_time', 'result_labels')


class EventLabelSerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = EventLabel
        fields = ('url', 'name', 'install_script', 'uninstall_script')


class SwarmMemberLogSerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = SwarmMemberLog
        fields = ('url', 'member', 'start_time', 'last_updated', 'log', 'resulting_changeset')
