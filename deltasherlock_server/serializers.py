from deltasherlock_server import models
from rest_framework import serializers


class QueueItemSerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = models.QueueItem
        fields = ('url', 'id', 'status', 'last_updated', 'submission_time', 'result_labels')


class EventLabelSerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = models.EventLabel
        fields = ('url', 'name', 'version', 'platform',
                  'cloud', 'install_script', 'uninstall_script')


class ChangesetWrapperSerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = models.ChangesetWrapper
        fields = ('url', 'labels', 'predicted_quantity', 'open_time', 'close_time', 'last_updated')


class SwarmMemberSerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = models.SwarmMember
        fields = ('url', 'hostname', 'status', 'ip', 'attached_rq_queues')
        read_only_fields = ('hostname',)


class SwarmMemberLogSerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = models.SwarmMemberLog
        fields = ('url', 'member', 'timestamp', 'log', 'log_type', 'resulting_changeset')
