"""
Create your "models" or datatypes here. These classes determine how the database
is structured, so you must run "python manage.py makemigrations" and "python
manage.py migrate" after making any significant changes here.
"""
import uuid
import pytz
from copy import copy
from datetime import datetime
from django.db import models
from django.urls import reverse
from django.contrib import admin
from simple_history.models import HistoricalRecords
from simple_history.admin import SimpleHistoryAdmin
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


class EventLabel(models.Model):
    """
    Used to hold "event" (usually an app installation) labels
    """
    PLATFORM_CHOICES = (
        ('CT7', 'CentOS 7'),
        ('UBX', 'Ubuntu Xenial'),
        ('UBT', 'Ubuntu Trusty'),
        ('UBP', 'Ubuntu Precise')
    )
    GROUP_CHOICES = (
        ('RP', 'Repository Packages'),
        ('MI', 'Manual Installations'),
        ('VD', 'Version Detection')
    )
    name = models.CharField(max_length=255)
    group = models.CharField(max_length=2, choices=GROUP_CHOICES, default='RP')
    version = models.CharField(max_length=255)
    platform = models.CharField(max_length=3, choices=PLATFORM_CHOICES, default='UBX')
    cloud = models.CharField(max_length=3, choices=CLOUD_CHOICES, default='IBM')

    install_script = models.TextField()
    uninstall_script = models.TextField()
    history = HistoricalRecords()

    def full_name(self):
        return "|".join([self.name, self.version, self.platform, self.cloud])

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
    list_display = ('name', 'group', 'version', 'platform', 'cloud')


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
    disk_type = models.CharField(max_length=2, choices=DISK_TYPE_CHOICES, default='SD', verbose_name="Disk type (for GCE)")
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
        # Use OpenStack Compute API to create instance
        try:
            userdata = self.configuration.replace("%HOSTNAME%", self.hostname).replace("%URL%", reverse("swarmmember-detail", args=[self.id]))
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
            insert_response = compute.instances().insert(project=GCE_CONF['project'], zone = GCE_CONF['zone'], body=config).execute()
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
                self.__get_compute().instances().delete(project=GCE_CONF['project'], zone = GCE_CONF['zone'], instance=self.hostname).execute()
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
    list_display = ('log_type', 'member', 'timestamp')
