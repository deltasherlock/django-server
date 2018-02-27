"""
Create your "models" or datatypes here. These classes determine how the database
is structured, so you must run "python manage.py makemigrations" and "python
manage.py migrate" after making any significant changes here.
"""
import uuid
import pytz
import pickle
from copy import copy
from hashlib import md5
from datetime import datetime
from django import forms
from django.db import models
from django.urls import reverse
from django.contrib import admin
from django.core import exceptions
from django.utils.text import capfirst
from multiselectfield import MultiSelectField
from simple_history.models import HistoricalRecords
from simple_history.admin import SimpleHistoryAdmin
from deltasherlock.server.learning import MLModel, MLAlgorithm
from deltasherlock.common.io import DSEncoder, DSDecoder, uid
from deltasherlock.common.changesets import Changeset, ChangesetRecord
from deltasherlock.common.fingerprinting import Fingerprint, FingerprintingMethod


## TEMPORARY CONFIG AREA ##
# Settings can be stored here during development. During production, store them
# in an actual settings file
KAIZEN_CONF = {
    'version': "2",
    'username': "abyrne19",
    'password': "y2gsSNguCQ0POoWw",
    'projid': "e363bb31c52640e59a840bc8504eddb4",
    'authurl': "https://keystone-kaizen.massopen.cloud:5000/v2.0",
    'keypair': "swarm_shared",
    'avalzone': "nova",
    'secgrps': ['default']
}
ENGAGE1_CONF = {
    'version': "2",
    'username': "abyrne19@bu.edu",
    'password': "z#31S*dC6c@f",
    'projid': "1539796bf0fe4129871ec444b03d96b3",
    'authurl': "https://engage1.massopen.cloud:5000/v2.0",
    'keypair': "swarm-shared",
    'avalzone': "nova",
    'secgrps': ['default']
}
BLUEMIX_CONF = {}
GCE_CONF = {
    'project': 'silver-bullet-bu',
    'region': 'us-central1',
    'zone': 'us-central1-a',
    'serviceacct': 'default'
}


CLOUD_CHOICES = (
    ('MCK', 'MOC Kaizen'),
    ('MCE', 'MOC Engage1'),
    ('IBM', 'IBM BlueMix'),
    ('GCE', 'Google Compute Engine'),
)

PLATFORM_CHOICES = (
    ('CT7', 'CentOS 7'),
    ('UBX', 'Ubuntu Xenial'),
    ('UBT', 'Ubuntu Trusty'),
    ('UBP', 'Ubuntu Precise')
)
GROUP_CHOICES = (
    ('RP', 'Repository Packages'),
    ('MI', 'Manual Installations'),
    ('VD', 'Version Detection'),
    ('KS', 'Kitchen Sink')
)
PURPOSE_CHOICES = (
    ('TR', 'Training'),
    ('TS', 'Testing'),
    ('OT', 'Other')
)

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

# Same as note above: Ensure this matches up with
# deltasherlock.common.server.learning.MLAlgorithm
ML_ALGORITHM_CHOICES = (
    (0, 'undefined'),
    (1, 'logistic_regression'),
    (2, 'decision_tree'),
    (3, 'random_forest'),
    (4, 'svm_rbf'),
    (5, 'svm_linear'),
    (6, 'adaboost'),
    (7, 'gradient_boosting'),
)

class EventLabel(models.Model):
    """
    Used to hold "event" (usually an app installation) labels
    """
    name = models.CharField(max_length=255)
    group = models.CharField(max_length=2, choices=GROUP_CHOICES, default='RP')
    purpose = models.CharField(max_length=2, choices=PURPOSE_CHOICES, default='TR')
    version = models.CharField(max_length=255)
    platform = models.CharField(max_length=3, choices=PLATFORM_CHOICES, default='UBX')
    cloud = models.CharField(max_length=3, choices=CLOUD_CHOICES, default='IBM')

    install_script = models.TextField()
    uninstall_script = models.TextField()
    history = HistoricalRecords()

    def full_name(self):
        return "|".join([self.name, self.version, self.purpose, self.platform, self.cloud])

    def get_dict(self):
        """
        Same as __dict__, but any non-native types (like django objects) are
        removed
        """
        sdict = self.__dict__
        if '_state' in sdict:
            sdict.pop('_state')
        return sdict

    def __str__(self):
        return self.full_name()


@admin.register(EventLabel)
class EventLabelAdmin(SimpleHistoryAdmin):
    list_display = ('name', 'group', 'purpose', 'version', 'platform', 'cloud')


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
            try:
                # Assume the label is an ID for an EventLabel
                self.labels.add(EventLabel.objects.get(id=label))
            except:
                # So it's not. Try this
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
            output += str(event_label) + ", "
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
        return "FP" + str(self.id) + " labeled " + str(self.get_labels()) + " (P.Qty: " + str(self.predicted_quantity) + ", Method: " + str(self.method) + ") originating from CS" + str(self.origin_changeset_id)


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
        cloud_id, status, and ip) will be left blank/at their default, even
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
            # Now set some fields
            new_member.cloud_id = ''
            new_member.status = 'PC'
            new_member.hostname += '-' + uid(size=4).lower()
            new_member.ip = None
            new_member.save()

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
    do_create_pending.short_description = "Create all pending members of selected swarms"

    def do_terminate_running(self, request, queryset):
        for swarm in queryset:
            swarm.terminate_running()
    do_terminate_running.short_description = "Terminate all running members of selected swarms"

    def do_terminate_all(self, request, queryset):
        for swarm in queryset:
            swarm.terminate_all()
    do_terminate_all.short_description = "Terminate all non-pending members of selected swarms"


class SwarmMember(models.Model):
    STATUS_CHOICES = (
        ('PC', 'Pending Creation'),
        ('CR', 'Creating'),
        ('RN', 'Running'),  # Reaches this state after instance phones in
        ('TM', 'Terminated'),
        ('ER', 'Error'),
    )
    DISK_TYPE_CHOICES = (
        ('SD', 'Solid State'),
        ('HD', 'Traditional'),
    )
    #openstack_id = models.UUIDField(null=True, blank=True, verbose_name="OpenStack Instance UUID")
    cloud_id = models.CharField(max_length=255, blank=True, verbose_name="Cloud instance ID")
    cloud = models.CharField(max_length=3, choices=CLOUD_CHOICES, default='IBM')
    status = models.CharField(max_length=2, choices=STATUS_CHOICES, default='PC')
    hostname = models.CharField(max_length=255, unique=True)
    ip = models.GenericIPAddressField(blank=True, null=True, verbose_name="IP Address")
    image = models.CharField(max_length=255, verbose_name="Image name")
    flavor = models.CharField(max_length=255)
    disk_size = models.IntegerField(default=10, verbose_name="Disk size in GB (for GCE)")
    disk_type = models.CharField(max_length=2, choices=DISK_TYPE_CHOICES,
                                 default='SD', verbose_name="Disk type (for GCE)")
    swarm = models.ForeignKey(Swarm, null=True, blank=True, on_delete=models.SET_NULL)
    configuration = models.TextField(blank=True, verbose_name="Cloud-init user data")
    comment = models.CharField(max_length=255, blank=True)
    history = HistoricalRecords()

    def attached_rq_queues(self):
        queues = ["-".join([self.get_swarm_name(), self.hostname, "task"]),
                  "-".join([self.get_swarm_name(), self.hostname, "networking"]),
                  "-".join([self.get_swarm_name(), self.hostname, "auxiliary"])]
        return queues

    def __get_nova(self):
        """
        Return the OpenStack API Nova object
        """
        from novaclient import client
        if self.cloud == 'MCK':
            return client.Client(KAIZEN_CONF['version'], KAIZEN_CONF['username'], KAIZEN_CONF['password'], KAIZEN_CONF['projid'], KAIZEN_CONF['authurl'])
        elif self.cloud == 'MCE':
            return client.Client(ENGAGE1_CONF['version'], ENGAGE1_CONF['username'], ENGAGE1_CONF['password'], ENGAGE1_CONF['projid'], ENGAGE1_CONF['authurl'])
        else:
            # TODO throw an error since we're not using an openstack cloud
            return

    def __get_nova_server(self):
        """
        Return the OpenStack API Nova Server object for this instance. Only
        accesible while instance is running
        """
        if self.status != 'RN':
            # TODO throw an err
            pass
        else:
            return self.__get_nova().servers.get(self.cloud_id)

    def __get_compute(self):
        from googleapiclient.discovery import build
        return build('compute', 'v1')

    def __openstack_create(self):
        """
        Instructs OpenStack to create the new instance
        """
        try:
            userdata = self.configuration.replace("%HOSTNAME%", self.hostname).replace(
                "%URL%", reverse("swarmmember-detail", args=[self.id]))
            nova = self.__get_nova()
            if self.cloud == 'MCK':
                sg = KAIZEN_CONF['secgrps']
                az = KAIZEN_CONF['avalzone']
                kn = KAIZEN_CONF['keypair']
            else:
                sg = ENGAGE1_CONF['secgrps']
                az = ENGAGE1_CONF['avalzone']
                kn = ENGAGE1_CONF['keypair']

            srv = nova.servers.create(name=self.hostname,
                                      image=nova.glance.find_image(self.image),
                                      flavor=nova.flavors.find(name=self.flavor),
                                      userdata=userdata,
                                      meta={"member-id": str(self.id),
                                            "member-url": reverse("swarmmember-detail", args=[self.id])},
                                      security_groups=sg,
                                      availability_zone=az,
                                      key_name=kn)
            self.cloud_id = srv.id
            # while 'standard' not in self.__get_nova().servers.get(srv.id).addresses:
            #     # Block until we can at least get an IP address
            #     pass
            # self.ip = srv.addresses['standard'][0]['addr']
        except:
            # TODO Throw an err
            self.status = 'ER'
            raise
        finally:
            self.save()

    def __gce_create(self):
        """
        TODO: Instructs Google Compute Engine (GCE) to create this instance
        """
        userdata = self.configuration.replace("%HOSTNAME%", self.hostname)
        config = {
            "name": self.hostname,
            "minCpuPlatform": "Automatic",
            "machineType": "projects/" + GCE_CONF['project'] + "/zones/" + GCE_CONF['zone'] + "/machineTypes/" + self.flavor,
            "metadata": {
                "items": [
                    {
                        "key": "user-data",
                        "value": userdata
                    },
                    {
                        "key": "member-id",
                        "value": str(self.id)
                    },
                    {
                        "key": "member-url",
                        "value": reverse("swarmmember-detail", args=[self.id])
                    }
                ]
            },
            "labels": {
                "swarm": self.get_swarm_name()
            },
            "disks": [
                {
                    "type": "PERSISTENT",
                    "boot": True,
                    "mode": "READ_WRITE",
                    "autoDelete": True,
                    "deviceName": self.hostname,
                    "initializeParams": {
                        "sourceImage": "projects/" + GCE_CONF['project'] + "/global/images/" + self.image,
                        "diskType": "projects/" + GCE_CONF['project'] + "/zones/" + GCE_CONF['zone'] + "/diskTypes/pd-ssd",
                        "diskSizeGb": self.disk_size
                    }
                }
            ],
            "canIpForward": False,
            "networkInterfaces": [
                {
                    "network": "projects/" + GCE_CONF['project'] + "/global/networks/default",
                    "subnetwork": "projects/" + GCE_CONF['project'] + "/regions/" + GCE_CONF['region'] + "/subnetworks/default",
                    "accessConfigs": [
                        {
                            "name": "External NAT",
                            "type": "ONE_TO_ONE_NAT"
                        }
                    ],
                    "aliasIpRanges": []
                }
            ],
            "scheduling": {
                "preemptible": False,
                "onHostMaintenance": "MIGRATE",
                "automaticRestart": True
            },
            "serviceAccounts": [
                {
                    "email": GCE_CONF['serviceacct'],
                    "scopes": [
                        "https://www.googleapis.com/auth/devstorage.read_only",
                        "https://www.googleapis.com/auth/logging.write",
                        "https://www.googleapis.com/auth/monitoring.write",
                        "https://www.googleapis.com/auth/servicecontrol",
                        "https://www.googleapis.com/auth/service.management.readonly",
                        "https://www.googleapis.com/auth/trace.append"
                    ]
                }
            ]
        }

        try:
            compute = self.__get_compute()
            insert_response = compute.instances().insert(
                project=GCE_CONF['project'], zone=GCE_CONF['zone'], body=config).execute()
            self.cloud_id = insert_response['targetId']
            # TODO Log response from API (do this for all clouds)
        except:
            # TODO Throw an err
            self.status = 'ER'
            raise
        finally:
            self.save()

    def __bluemix_create(self):
        """
        TODO: Instructs IBM BlueMix to create this instance
        """
        pass

    def create(self):
        """
        Instructs the appropriate cloud platform to create this instance
        """
        if self.status != 'PC' and self.status != 'TM':
            # TODO Throw an err since the instance is already Running
            pass
        else:
            self.status = 'CR'
            self.save()

            if self.cloud == "MCK" or self.cloud == "MCE":
                self.__openstack_create()
            elif self.cloud == "GCE":
                self.__gce_create()
            elif self.cloud == "IBM":
                self.__bluemix_create()

    def check_in(self, instance_ip):
        """
        Called via API by instance after it has fully booted and is ready to
        accept tasks
        """
        self.ip = instance_ip
        self.status = 'RN'
        self.save()

        # Return the names of the RQ task queues to attatch to
        return self.attached_rq_queues()

    def reboot(self):
        """
        Instructs OpenStack to reboot the instance
        """
        if self.cloud == "MCK" or self.cloud == "MCE":
            # OpenStack
            self.__get_nova_server().reboot()
        elif self.cloud == "GCE":
            # Google Compute Engine
            pass
        elif self.cloud == "IBM":
            # IBM BlueMix
            pass
        else:
            # TODO: throw error Unknown cloud option
            pass

    def terminate(self):
        """
        Instructs OpenStack to terminate the instance. Also erases the boot
        volume
        """
        try:
            if self.cloud == "MCK" or self.cloud == "MCE":
                self.__get_nova().servers.get(self.cloud_id).delete()
            elif self.cloud == "GCE":
                # Google Compute Engine
                self.__get_compute().instances().delete(project=GCE_CONF['project'], zone=GCE_CONF[
                    'zone'], instance=self.hostname).execute()
            elif self.cloud == "IBM":
                # IBM BlueMix
                pass
            else:
                # TODO: throw error Unknown cloud option
                pass

            self.ip = None
            self.status = 'TM'
        except:
            # TODO throw an error
            self.status = 'ER'
            raise
        finally:
            self.save()

    def rebuild(self):
        """
        Terminates and re-creates this instance
        """
        self.terminate()
        self.create()

    def get_swarm_name(self):
        try:
            return self.swarm.name
        except:
            return "none"
    get_swarm_name.short_description = "Swarm"

    def __str__(self):
        return self.hostname + " of " + self.get_swarm_name()


@admin.register(SwarmMember)
class SwarmMemberAdmin(SimpleHistoryAdmin):
    list_display = ('hostname', 'status', 'get_swarm_name', 'ip', 'cloud', 'comment', 'id')
    actions = ['do_create', 'do_set_running', 'do_set_pending', 'do_terminate', 'do_rebuild']

    def do_create(self, request, queryset):
        for member in queryset:
            member.create()
    do_create.short_description = "Create selected members"

    def do_terminate(self, request, queryset):
        for member in queryset:
            member.terminate()
    do_terminate.short_description = "Terminate selected members"

    def do_rebuild(self, request, queryset):
        for member in queryset:
            member.rebuild()
    do_rebuild.short_description = "Rebuild selected members"

    def do_set_running(self, request, queryset):
        for member in queryset:
            member.status = 'RN'
            member.save()
    do_set_running.short_description = "Set status of selected members to Running"

    def do_set_pending(self, request, queryset):
        for member in queryset:
            member.status = 'PC'
            member.save()
    do_set_pending.short_description = "Set status of selected members to Pending Creation"


class SwarmMemberLog(models.Model):
    LOG_TYPE_CHOICES = (
        ('IN', 'Installation'),
        ('NT', 'Notification'),
        ('ER', 'Error'),
        ('OT', 'Other'),
    )
    log_type = models.CharField(max_length=2, choices=LOG_TYPE_CHOICES, default='IN')
    member = models.ForeignKey(SwarmMember, null=True, on_delete=models.SET_NULL)
    timestamp = models.DateTimeField(auto_now_add=True)
    log = models.TextField(blank=True)
    resulting_changeset = models.ForeignKey(
        ChangesetWrapper, null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self):
        return self.log_type + ": " + str(self.timestamp)


@admin.register(SwarmMemberLog)
class SwarmMemberLogAdmin(SimpleHistoryAdmin):
    list_display = ('log_type', 'member', 'timestamp', 'id')
    exclude = ['resulting_changeset']


class MLModelWrapper(models.Model):
    """
    Wraps around a deltasherlock.learning.MLModel. Unlike a DeltaSherlockWrapper,
    the MLModel object is pickled and saved to file instead of in the database
    """
    fingerprints = models.ManyToManyField(FingerprintWrapper)
    labels = models.ManyToManyField(EventLabel, blank=True)
    file_path = models.CharField(max_length=256)
    md5_hash = models.CharField(max_length=32)
    ml_algorithm = models.IntegerField(choices=ML_ALGORITHM_CHOICES, default=0)
    method = models.IntegerField(choices=FINGERPRINTING_METHOD_CHOICES, default=0)

    @classmethod
    def generate(cls, fingerprint_wrappers, algorithm, file_path, method = None):
        mlmw = cls(file_path = file_path)

        unwrapped_fingerprints = []
        for fpw in fingerprint_wrappers:
            unwrapped_fingerprints.append(fpw.unwrap())

        mlm = MLModel(unwrapped_fingerprints, MLAlgorithm(algorithm), FingerprintingMethod(method))
        mlmw.wrap(mlm)

        mlmw.fingerprints.set(fingerprint_wrappers)
        mlmw.save()
        return mlmw

    def wrap(self, object_to_wrap):
        self.ml_algorithm = object_to_wrap.algorithm.value
        self.method = object_to_wrap.method.value

        with open(self.file_path, "wb") as f:
            pickle.dump(object_to_wrap, f)

        self.md5_hash = self.__md5(self.file_path)
        self.save()

        for label_id in set(object_to_wrap.labels):
            el = EventLabel.objects.get(id=label_id)
            self.labels.add(el)

        self.save()

    def unwrap(self, verify_hash = False):
        if verify_hash:
            assert self.md5_hash == self.__md5(self.file_path)
        with open(self.file_path, "rb") as f:
            return pickle.load(f)

    def __md5(self, fname):
        """
        Borrowed from https://stackoverflow.com/a/3431838
        """
        hash_md5 = md5()
        with open(fname, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def __str__(self):
        return "M" + str(self.method) + ":A" + str(self.ml_algorithm) + " with " + str(self.labels.count()) + " labels"


class ExperimentResult(models.Model):
    """
    Used for research. Represents a single prediction of a single fingerprint
    """
    ml_model = models.ForeignKey(MLModelWrapper, models.PROTECT, null=True, blank=True)
    fingerprint = models.ForeignKey(FingerprintWrapper, models.PROTECT, null=True, blank=True)
    predictions = models.ManyToManyField(EventLabel, blank=True)

    true_positive_count = models.IntegerField(default=0)
    true_negative_count = models.IntegerField(default=0)
    false_positive_count = models.IntegerField(default=0)
    false_negative_count = models.IntegerField(default=0)

    partial = models.BooleanField(default=False)

    timestamp = models.DateTimeField(auto_now_add=True)

    @classmethod
    def create(cls, ml_model, fingerprint, predictions, partial=False):
        """
        Generates an ExperimentResult from necessary inputs. Note that parameters
        are should be in their Django types (i.e. MLModel, FingerprintWrapper), not
        their "native" deltasherlock base types
        """
        er = cls()
        er.save()
        er.ml_model = ml_model
        er.fingerprint = fingerprint
        er.predictions = predictions
        er.true_positive_count = len(er.get_true_positives())
        er.true_negative_count = len(er.get_true_negatives())
        er.false_positive_count = len(er.get_false_positives())
        er.false_negative_count = len(er.get_false_negatives())
        er.partial = partial
        er.save()
        return er

    def get_true_positives(self):
        return set(self.fingerprint_names()) & set(self.prediction_names())

    def get_true_negatives(self):
        return set(set(self.model_label_names()) - set(self.fingerprint_names())) - set(self.prediction_names())

    def get_false_positives(self):
        return set(self.prediction_names()) - set(self.fingerprint_names())

    def get_false_negatives(self):
        return set(self.fingerprint_names()) - set(self.prediction_names())

    def fingerprint_names(self):
        fingerprint_label_names = []
        for elabel in self.fingerprint.labels.all():
            if self.partial and elabel.group == 'VD':
                # Hack to allow partial version detection
                fingerprint_label_names.append(''.join(i for i in elabel.name if not i.isdigit()))
            else:
                fingerprint_label_names.append(elabel.name)
        return fingerprint_label_names

    def prediction_names(self):
        prediction_label_names = []
        for elabel in self.predictions.all():
            if self.partial and elabel.group == 'VD':
                # Hack to allow partial version detection
                prediction_label_names.append(''.join(i for i in elabel.name if not i.isdigit()))
            else:
                prediction_label_names.append(elabel.name)
        return prediction_label_names

    def model_label_names(self):
        model_label_names = []
        for elabel in self.ml_model.labels.all():
            if self.partial and elabel.group == 'VD':
                # Hack to allow partial version detection
                model_label_names.append(''.join(i for i in elabel.name if not i.isdigit()))
            else:
                model_label_names.append(elabel.name)
        return model_label_names

    def __str__(self):
        return str(self.fingerprint_names()) + ":" + str(self.prediction_names())

class Experiment(models.Model):
    """
    Used for research. Represents a single experiment, consisting of collections
    of training and testing fingerprints, a trained model, and a set of
    ExperimentResults
    """
    train_group = MultiSelectField(max_length=255, blank=True, choices=GROUP_CHOICES)
    test_group = MultiSelectField(max_length=255, blank=True, choices=GROUP_CHOICES)

    train_purpose = MultiSelectField(max_length=255, blank=True, choices=PURPOSE_CHOICES)
    test_purpose = MultiSelectField(max_length=255, blank=True, choices=PURPOSE_CHOICES)

    train_platform = MultiSelectField(max_length=255, blank=True, choices=PLATFORM_CHOICES)
    test_platform = MultiSelectField(max_length=255, blank=True, choices=PLATFORM_CHOICES)

    train_cloud = MultiSelectField(max_length=255, blank=True, choices=CLOUD_CHOICES)
    test_cloud = MultiSelectField(max_length=255, blank=True, choices=CLOUD_CHOICES)

    train_fingerprints = models.ManyToManyField(FingerprintWrapper, related_name="experiment_train_set", blank=True)
    test_fingerprints = models.ManyToManyField(FingerprintWrapper, related_name="experiment_test_set", blank=True)

    train_quantity = models.PositiveSmallIntegerField(null=True, blank=True)
    test_quantity = models.PositiveSmallIntegerField(null=True, blank=True)

    results = models.ManyToManyField(ExperimentResult, blank=True)

    comment = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    fp_method = models.IntegerField(choices=FINGERPRINTING_METHOD_CHOICES, default=0)
    ml_algorithm = models.IntegerField(choices=ML_ALGORITHM_CHOICES, default=0)
    ml_model = models.ForeignKey(MLModelWrapper, models.SET_NULL, null=True, blank=True)

    def gather_fingerprints(self):
        # Start with filter by FP method
        tr_fprints = FingerprintWrapper.objects.filter(method=self.fp_method)
        if len(self.train_group) > 0:
            tr_fprints = tr_fprints.filter(labels__group__in=self.train_group)
        if len(self.train_purpose) > 0:
            tr_fprints = tr_fprints.filter(labels__purpose__in=self.train_purpose)
        if len(self.train_platform) > 0:
            tr_fprints = tr_fprints.filter(labels__platform__in=self.train_platform)
        if len(self.train_cloud) > 0:
            tr_fprints = tr_fprints.filter(labels__cloud__in=self.train_cloud)
        if self.train_quantity is not None and self.train_quantity > 0:
            # Add custom annotation (lookup field) to filter by label count
            tr_fprints = tr_fprints.annotate(num_labels=models.Count('labels'))
            tr_fprints = tr_fprints.filter(num_labels=self.train_quantity)


        ts_fprints = FingerprintWrapper.objects.filter(method=self.fp_method)
        if len(self.test_group) > 0:
            ts_fprints = ts_fprints.filter(labels__group__in=self.test_group)
        if len(self.test_purpose) > 0:
            ts_fprints = ts_fprints.filter(labels__purpose__in=self.test_purpose)
        if len(self.test_platform) > 0:
            ts_fprints = ts_fprints.filter(labels__platform__in=self.test_platform)
        if len(self.test_cloud) > 0:
            ts_fprints = ts_fprints.filter(labels__cloud__in=self.test_cloud)
        if self.test_quantity is not None and self.test_quantity > 0:
            # Add custom annotation (lookup field) to filter by label count
            ts_fprints = ts_fprints.annotate(num_labels=models.Count('labels'))
            ts_fprints = ts_fprints.filter(num_labels=self.test_quantity)

        self.train_fingerprints.set(tr_fprints, clear=True)
        self.test_fingerprints.set(ts_fprints, clear=True)

        self.save()

    def generate_ml_model(self, filepath):
        self.ml_model = MLModelWrapper.generate(self.train_fingerprints.all(), self.ml_algorithm, filepath, self.fp_method)
        self.save()

    def generate_results(self, clear = True, override_quantity = None, partial = False):
        """
        Runs the Experiment, saving ExperimentResults as we go. If clear is True,
        then any prior results are deleted before running the experiment. If
        override_quantity is an integer n, we force the model to give n predictions
        for each sample

        We assume here that all prior steps have been executed successfully. This
        includes running gather_fingerprints() and generate_ml_model()
        """
        mlm = self.ml_model.unwrap()

        if clear:
            self.results.all().delete()

        for fpw in self.test_fingerprints.all():
            try:
                self.results.add(ExperimentResult.create(self.ml_model, fpw, mlm.predict(fpw.unwrap(), override_quantity=override_quantity), partial=partial))
            except:
                print("Skipped " +str(fpw))

        self.save()

    def print_analysis(self):
        """
        Prints F1 scores, hamming, etc. Run this after generate_results()
        """
        actual_labels = 0
        predictions_made = 0
        correct_predictions = 0
        f1_score = 0
        app_stats = {}

        for er in self.results.all():
            actual_labels += er.fingerprint_names().count()
            predictions_made += er.prediction_names().count()
            correct_predictions += er.true_positive_count

            # App Stats
            for tf_label in er.fingerprint_names():
                try:
                    app_stats[tf_label]['true_frequency'] += 1
                except:
                    app_stats[tf_label] = {'true_frequency': 1, 'predicted_frequency': 0, 'true_positives': 0, 'true_negatives': 0, 'false_positives': 0, 'false_negatives': 0}

            for pf_label in er.prediction_names():
                try:
                    app_stats[pf_label]['predicted_frequency'] += 1
                except:
                    app_stats[pf_label] = {'true_frequency': 0, 'predicted_frequency': 1, 'true_positives': 0, 'true_negatives': 0, 'false_positives': 0, 'false_negatives': 0}

            for tp_label in er.get_true_positives():
                try:
                    app_stats[tp_label]['true_positives'] += 1
                except:
                    app_stats[tp_label] = {'true_frequency': 0, 'predicted_frequency': 0, 'true_positives': 1, 'true_negatives': 0, 'false_positives': 0, 'false_negatives': 0}

            for tn_label in er.get_true_negatives():
                try:
                    app_stats[tn_label]['true_negatives'] += 1
                except:
                    app_stats[tn_label] = {'true_frequency': 0, 'predicted_frequency': 0, 'true_positives': 0, 'true_negatives': 1, 'false_positives': 0, 'false_negatives': 0}

            for fp_label in er.get_false_positives():
                try:
                    app_stats[fp_label]['false_positives'] += 1
                except:
                    app_stats[fp_label] = {'true_frequency': 0, 'predicted_frequency': 0, 'true_positives': 0, 'true_negatives': 0, 'false_positives': 1, 'false_negatives': 0}

            for fn_label in er.get_false_negatives():
                try:
                    app_stats[fn_label]['false_negatives'] += 1
                except:
                    app_stats[fn_label] = {'true_frequency': 0, 'predicted_frequency': 0, 'true_positives': 0, 'true_negatives': 0, 'false_positives': 0, 'false_negatives': 1}


        precision = float(correct_predictions) / predictions_made
        recall = float(correct_predictions) / actual_labels

        if precision + recall > 0:
            f1_score = 2 * (precision * recall) / (precision + recall)

        hamming = float(correct_predictions) / self.test_fingerprints.count()

        print("Predictions Made: " + str(predictions_made) + " | " )
        print("Precision: " + str(precision) + " | Recall: " + str(recall))
        print("F1 Score: " + str(f1_score) + " | Hamming: " + str(hamming))

        return app_stats


    def __format_list(self, in_list):
        if len(in_list) == 0:
            return "*"
        elif len(in_list) == 1:
            return in_list[0]
        else:
            return str(in_list)


    def get_name(self):
        train_str = "-".join(map(self.__format_list, [self.train_group, self.train_platform, self.train_purpose]))
        test_str = "-".join(map(self.__format_list, [self.test_group, self.test_platform, self.test_purpose]))
        return train_str + ":" + test_str
    get_name.short_description = "Name"

    def result_count(self):
        return str(self.results.count())

    def __str__(self):
        return self.get_name()


@admin.register(Experiment)
class ExperimentAdmin(SimpleHistoryAdmin):
    list_display = ('id', 'get_name', 'ml_algorithm', 'result_count', 'comment', 'timestamp')
    exclude = ('train_fingerprints', 'test_fingerprints', 'results')
