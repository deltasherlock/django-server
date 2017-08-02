"""
Create your "models" or datatypes here. These classes determine how the database
is structured, so you must run "python manage.py makemigrations" and "python
manage.py migrate" after making any significant changes here.
"""
import uuid
import pytz
from copy import copy
from datetime import datetime
from novaclient import client
from django.db import models
from django.contrib import admin
from simple_history.models import HistoricalRecords
from simple_history.admin import SimpleHistoryAdmin
from deltasherlock.common.io import DSEncoder, DSDecoder, uid
from deltasherlock.common.changesets import Changeset, ChangesetRecord
from deltasherlock.common.fingerprinting import Fingerprint, FingerprintingMethod

OPENSTACK_VERSION = "2"
OPENSTACK_USERNAME = "abyrne19"
OPENSTACK_PASSWORD = "y2gsSNguCQ0POoWw"
OPENSTACK_PROJID = "e363bb31c52640e59a840bc8504eddb4"
OPENSTACK_AUTHURL = "https://keystone-kaizen.massopen.cloud:5000/v2.0"
OPENSTACK_KEYPAIR = "swarm_shared"
OPENSTACK_AVALZONE = "nova"
OPENSTACK_SECGRPS = ['default']


class EventLabel(models.Model):
    """
    Used to hold "event" (usually an app installation) labels
    """
    name = models.CharField(max_length=255, primary_key=True)
    install_script = models.TextField()
    uninstall_script = models.TextField()
    history = HistoricalRecords()

    def __str__(self):
        return self.name


@admin.register(EventLabel)
class EventLabelAdmin(SimpleHistoryAdmin):
    list_display = ['name']


class QueueItem(models.Model):
    """
    Used to represent a client request that was successfully used to create
    an RQ job. Currently, one QueueItem represents one submitted Fingerprint.
    """
    STATUS_CHOICES = (
        ('PN', 'Pending'),
        ('RN', 'Running'),
        ('FN', 'Finished'),
        ('FL', 'Failed'),
    )

    #id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    status = models.CharField(
        max_length=2, choices=STATUS_CHOICES, default='PN')
    last_updated = models.DateTimeField(auto_now=True)
    client_ip = models.GenericIPAddressField(
        verbose_name="Submitting Client IP")
    submission_time = models.DateTimeField(auto_now_add=True)
    endpoint_url = models.URLField()
    parameters = models.CharField(max_length=255, blank=True)
    error_message = models.CharField(max_length=511, blank=True)
    request_body = models.TextField(verbose_name="Full HTTP Request Text")
    rq_id = models.CharField(max_length=50, verbose_name="RQ Job ID")
    result_labels = models.ManyToManyField(
        EventLabel, verbose_name="Predicted Labels", blank=True)
    history = HistoricalRecords()

    def from_request(self, request, rq_id: str, request_body: str = None) -> int:
        """
        Extract data from a DRF Request object and commit to database

        :param request: a Django Rest Framework Request object that was
        previously successfully submitted to RQ
        :param rq_id: the ID string assigned by RQ
        :return: the QueueItem's ID
        """
        self.client_ip = request.META['REMOTE_ADDR']
        self.endpoint_url = request.data['endpoint_url']
        self.parameters = request.data['parameters']
        self.rq_id = rq_id
        self.request_body = request_body
        self.save()
        return self.id

    def rq_running(self):
        """
        Called when an RQ worker dials into Django for the first time to let us
        know that its running
        """
        self.status = 'RN'
        self.save()

    def rq_complete(self, labels: list = None, error: str = None):
        """
        Called when an RQ worker that's been "dialed in" to Django has completed
        this QueueItem.

        :param labels: the list of predicted labels
        :param error: the error message to be logged if this job failed. If this
        is None, we assume the job was successful
        """
        if error is None:
            self.status = 'FN'
        else:
            self.status = 'FL'
            self.error_message = str(error)

        for label in labels:
            # See if there's already an EventLabel in the DB for that
            label_qset = EventLabel.objects.filter(name=label)
            event_label = None

            if not label_qset.exists():
                # Create one if it doesn't exist
                event_label = EventLabel.objects.create(name=label)
            else:
                # Use the existing one if it does
                event_label = label_qset[0]

            # Add the relationship
            self.result_labels.add(event_label)

        self.save()

    def __str__(self):
        return str(self.status) + ": " + str(self.submission_time) + ", " + str(self.client_ip) + " sent " + str(self.id)

    class Meta:
        ordering = ['-submission_time']


@admin.register(QueueItem)
class QueueItemAdmin(SimpleHistoryAdmin):
    list_display = ('status', 'id', 'client_ip', 'submission_time')


class DeltaSherlockWrapper(models.Model):
    """
    An abstract base class for a "database wrapper" around a standard DeltaSherlock
    type (Fingerprint or Changeset). Essentially, this allows the metadata of
    most types to be represented by their own fields (making them searchable),
    while the "meat" of the type (ie. the numpy array inside a Fingerprint) is
    stored in a serialized JSON format. The original type can always be "wrapped"
    and "unwrapped" via .wrap() and .unwrap()
    """
    labels = models.ManyToManyField(EventLabel, blank=True)
    predicted_quantity = models.IntegerField()
    json_data = models.TextField()
    history = HistoricalRecords(inherit=True)
    last_updated = models.DateTimeField(auto_now=True)

    def wrap(self, object_to_wrap):
        """
        Creates a "wrapped" version of the input object by extracting relevant
        metadata and storing a serialized copy of the original object

        :param object_to_wrap: the Changeset or Fingerprint to be wrapped
        """
        self.predicted_quantity = object_to_wrap.predicted_quantity
        self.json_data = DSEncoder().encode(object_to_wrap)
        self.save()
        # Now that we have an ID, we can add labels

        # Loop through each label in the raw object
        for label in object_to_wrap.labels:
            # See if there's already an EventLabel in the DB for that
            label_qset = EventLabel.objects.filter(name=label)
            event_label = None

            if not label_qset.exists():
                # Create one if it doesn't exist
                event_label = EventLabel.objects.create(name=label)
            else:
                # Use the existing one if it does
                event_label = label_qset[0]

            # Add the relationship
            self.labels.add(event_label)

        self.save()

    def unwrap(self):
        """
        Produce the original, "unwrapped" object using the serialized copy stored
        in the database

        :return: the original Changeset or Fingerprint
        """
        obj = DSDecoder().decode(self.json_data)
        obj.db_id = self.id
        return obj

    def get_labels(self):
        """
        Souped-up getter method to get a string containing all the EventLabels
        this wrapper is attached to. Useful for admin interface
        """
        output = ''
        for event_label in self.labels.all():
            output += str(event_label.name) + ", "
        return output
    get_labels.short_description = "Event Labels"

    class Meta:
        abstract = True


class ChangesetWrapper(DeltaSherlockWrapper):
    """
    A database wrapper around a Changeset object. See the docs for
    DeltaSherlockWrapper for more details.
    """
    open_time = models.DateTimeField()
    close_time = models.DateTimeField()

    def wrap(self, object_to_wrap):
        self.open_time = datetime.utcfromtimestamp(
            object_to_wrap.open_time).replace(tzinfo=pytz.utc)
        self.close_time = datetime.utcfromtimestamp(
            object_to_wrap.close_time).replace(tzinfo=pytz.utc)
        super().wrap(object_to_wrap)

    def __str__(self):
        return "CS" + str(self.id) + " labeled " + str(self.get_labels()) + " (P.Qty: " + str(self.predicted_quantity) + ", CT: " + str(self.close_time) + ")"


@admin.register(ChangesetWrapper)
class ChangesetWrapperAdmin(SimpleHistoryAdmin):
    list_display = ('id', 'get_labels', 'predicted_quantity', 'last_updated')


class FingerprintWrapper(DeltaSherlockWrapper):
    """
    A database wrapper around a Fingerprint object. See the docs for
    DeltaSherlockWrapper for more details.
    """
    # It's probably a good idea to make sure this always matches up with the
    # enum defined in deltasherlock.common.fingerprinting.FingerprintingMethod.
    # And in general, the numbering scheme should ALWAYS remain backward
    # compat.
    FINGERPRINTING_METHOD_CHOICES = (
        (0, 'undefined'),
        (1, 'histogram'),
        (2, 'filetree'),
        (3, 'histofiletree'),
        (4, 'neighbor'),
        (5, 'histoneighbor'),
        (6, 'filetreeneighbor'),
        (7, 'combined'),
    )

    method = models.IntegerField(
        choices=FINGERPRINTING_METHOD_CHOICES, default=0)
    origin_changeset = models.ForeignKey(
        ChangesetWrapper, on_delete=models.SET_NULL, null=True, blank=True)

    def wrap(self, object_to_wrap):
        self.method = object_to_wrap.method.value
        try:
            self.origin_changeset = ChangesetWrapper.objects.get(
                id=object_to_wrap.cs_db_id)
        except:
            # undefined origin changeset
            pass
        super().wrap(object_to_wrap)

    def unwrap(self):
        # We have to override the default unwrap() because we need to set the
        # origin changeset ID
        obj = super().unwrap()
        obj.cs_db_id = self.origin_changeset_id
        return obj

    def __str__(self):
        return "FP" + str(self.id) + " labeled " + str(self.labels) + " (P.Qty: " + str(self.predicted_quantity) + ", Method: " + str(self.method) + ") originating from CS" + str(self.origin_changeset_id)


@admin.register(FingerprintWrapper)
class FingerprintWrapperAdmin(SimpleHistoryAdmin):
    list_display = ('id', 'get_labels', 'method', 'last_updated')


class Swarm(models.Model):
    name = models.CharField(max_length=255)
    date_created = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    def generate_members(self, quantity, member_model):
        """
        Generate a number of SwarmMembers based on a supplied model SwarmMember.
        The generated members will be carbon copies of the model, except a unique
        identifier will be appended to the hostname, and some fields (like
        openstack_id, status, and ip) will be left blank/at their default, even
        if they are populated in the model. The resulting SwarmMembers will be in
        the "Pending Creation" state and part of this Swarm.

        :param quantity: a positive integer indicating how many SwarmMembers should
        be generated
        :param member_model: a SwarmMember that will server as the "model" for
        the generated SwarmMembers
        """

        for i in range(quantity):
            # Grab a fresh copy of the member_model
            new_member = copy(member_model)

            # Set the primary_key to None, which effectively makes a db copy
            new_member.pk = None
            new_member.save()

            # Now set some fields
            new_member.openstack_id = None
            new_member.status = 'PC'
            new_member.hostname += '-' + uid(size=4)
            new_member.ip = None

            new_member.swarm = self

            new_member.save()

    def create_pending(self):
        """
        Runs the .create() method of all SwarmMembers in the Swarm that are in
        the 'Pending Creation' state
        """
        for member in SwarmMember.objects.filter(swarm=self, status='PC'):
            member.create()

    def terminate_running(self):
        """
        Runs the .terminate() method of all SwarmMembers in the Swarm that are in
        the 'Running' state
        """
        for member in SwarmMember.objects.filter(swarm=self, status='RN'):
            member.terminate()

    def terminate_all(self):
        """
        Runs the .terminate() method of all SwarmMembers in the Swarm that are
        not already terminated or pending creation
        """
        for member in SwarmMember.objects.filter(swarm=self).exclude(status__in=['TM', 'PC']):
            member.terminate()

    def get_num_members(self):
        return self.swarmmember_set.count()
    get_num_members.short_description = "Total Members"

    def get_num_pending(self):
        return self.swarmmember_set.filter(status='PC').count()
    get_num_pending.short_description = "Pending"

    def get_num_running(self):
        return self.swarmmember_set.filter(status='RN').count()
    get_num_running.short_description = "Running"


@admin.register(Swarm)
class SwarmAdmin(SimpleHistoryAdmin):
    list_display = ('name', 'get_num_members', 'get_num_pending',
                    'get_num_running', 'date_created', 'id')
    actions = ['do_create_pending', 'do_terminate_running', 'do_terminate_all']

    def do_create_pending(self, request, queryset):
        for swarm in queryset:
            swarm.create_pending()
    do_create_pending.short_description = "Create all members pending creation in selected swarms"

    def do_terminate_running(self, request, queryset):
        for swarm in queryset:
            swarm.terminate_running()
    do_terminate_running.short_description = "Terminate all running members in selected swarms"

    def do_terminate_all(self, request, queryset):
        for swarm in queryset:
            swarm.terminate_all()
    do_terminate_all.short_description = "Terminate all members in selected swarms"


class SwarmMember(models.Model):
    STATUS_CHOICES = (
        ('PC', 'Pending Creation'),
        ('CR', 'Creating'),
        ('RN', 'Running'),  # Reaches this state after instance phones in
        ('TM', 'Terminated'),
        ('ER', 'Error'),
    )
    SOURCE_CHOICES = (
        ('snapshot', 'Snapshot'),
        ('image', 'Image'),
        ('volume', 'Volume'),
    )
    openstack_id = models.UUIDField(null=True, blank=True, verbose_name="OpenStack Instance UUID")
    status = models.CharField(
        max_length=2, choices=STATUS_CHOICES, default='PC')
    hostname = models.CharField(max_length=255)
    ip = models.GenericIPAddressField(blank=True, null=True)
    source_type = models.CharField(
        max_length=8, choices=SOURCE_CHOICES, default='image')
    source_uuid = models.UUIDField(verbose_name="Source Device UUID")
    volume_size = models.IntegerField(default=20, verbose_name="Boot Volume Size (GB)")
    flavor = models.CharField(max_length=255)
    swarm = models.ForeignKey(Swarm, null=True, blank=True, on_delete=models.SET_NULL)
    configuration = models.TextField(blank=True)
    delete_on_termination = models.BooleanField(default=True)
    comment = models.CharField(max_length=255, blank=True)
    history = HistoricalRecords()

    def __get_nova(self):
        """
        Return the OpenStack API Nova object
        """
        return client.Client(OPENSTACK_VERSION, OPENSTACK_USERNAME, OPENSTACK_PASSWORD, OPENSTACK_PROJID, OPENSTACK_AUTHURL)

    def __get_server(self):
        """
        Return the OpenStack API Nova Server object for this instance. Only
        accesible while instance is running
        """
        if self.status != 'RN':
            # TODO throw an err
            pass
        else:
            return self.__get_nova().servers.get(self.openstack_id)

    def __get_block_dev_map(self):
        return [{"boot_index": "0",
                 "uuid": self.source_uuid,
                 "source_type": self.source_type,
                 "volume_size": self.volume_size,
                 "destination_type": "volume",
                 "delete_on_termination": self.delete_on_termination}]

    def create(self):
        """
        Instructs OpenStack to create the new instance
        """
        if self.status != 'PC' and self.status != 'TM':
            # TODO Throw an err since the instance is already Running
            pass
        else:
            # Use OpenStack Compute API to create instance
            # try:
            self.status = 'CR'
            self.save()
            nova = self.__get_nova()
            srv = nova.servers.create(name=self.hostname,
                                      # image=nova.glance.find_image(
                                      #      self.image_name),
                                      image=None,
                                      flavor=nova.flavors.find(name=self.flavor),
                                      usrdata=self.configuration,
                                      meta={"member-id": str(self.id)},
                                      block_device_mapping_v2=self.__get_block_dev_map(),
                                      security_groups=OPENSTACK_SECGRPS,
                                      availability_zone=OPENSTACK_AVALZONE,
                                      key_name=OPENSTACK_KEYPAIR)
            self.openstack_id = srv.id
            # while 'standard' not in self.__get_nova().servers.get(srv.id).addresses:
            #     # Block until we can at least get an IP address
            #     pass
            # self.ip = srv.addresses['standard'][0]['addr']
            # except:
            #     # TODO Throw an err
            #     self.status = 'ER'
            self.save()

    def check_in(self, instance_ip):
        """
        Called via API by instance after it has fully booted and is ready to
        accept tasks
        """
        self.ip = instance_ip
        self.status = 'RN'
        self.save()

    def reboot(self):
        """
        Instructs OpenStack to reboot the instance
        """
        self.__get_server().reboot()

    def terminate(self):
        """
        Instructs OpenStack to terminate the instance. Also erases the boot
        volume
        """
        nova = self.__get_nova()
        # if self.delete_on_terminate:
        #     vol_id = nova.volumes.get_server_volumes(self.openstack_id)[0].id
        #     nova.volumes.delete_server_volume(self.openstack_id, volume_id=vol_id)
        nova.servers.get(self.openstack_id).delete()
        self.ip = None
        self.status = 'TM'
        self.save()

    def get_swarm_name(self):
        try:
            return self.swarm.name
        except:
            return "None"
    get_swarm_name.short_description = "Swarm"

    def __str__(self):
        return self.hostname + " of " + self.get_swarm_name()


@admin.register(SwarmMember)
class SwarmMemberAdmin(SimpleHistoryAdmin):
    list_display = ('hostname', 'status', 'get_swarm_name', 'ip', 'comment', 'id')
    actions = ['do_create', 'do_set_running', 'do_set_pending', 'do_terminate']

    def do_create(self, request, queryset):
        for member in queryset:
            member.create()
    do_create.short_description = "Create selected members"

    def do_terminate(self, request, queryset):
        for member in queryset:
            member.terminate()
    do_terminate.short_description = "Terminate selected members"

    def do_set_running(self, request, queryset):
        for member in queryset:
            member.status = 'RN'
            member.save()
    do_set_running.short_description = "Set status of selected members to Running"

    def do_set_pending(self, request, queryset):
        for member in queryset:
            member.status = 'RN'
            member.save()
    do_set_pending.short_description = "Set status of selected members to Pending Creation"


class SwarmMemberLog(models.Model):
    member = models.ForeignKey(SwarmMember, null=True, on_delete=models.SET_NULL)
    start_time = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    log = models.TextField(blank=True)
    resulting_changeset = models.ForeignKey(
        ChangesetWrapper, null=True, blank=True, on_delete=models.SET_NULL)
    history = HistoricalRecords()

    def __str__(self):
        return str(self.start_time) + " from " + self.member.hostname


@admin.register(SwarmMemberLog)
class SwarmMemberLogAdmin(SimpleHistoryAdmin):
    list_display = ('start_time', 'member')
