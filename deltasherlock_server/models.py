"""
Create your "models" or datatypes here. These classes determine how the database
is structured, so you must run "python manage.py makemigrations" and "python
manage.py migrate" after making any significant changes here.
"""
import uuid
import pytz
from datetime import datetime
from django.db import models
from deltasherlock.common.io import DSEncoder, DSDecoder
from deltasherlock.common.changesets import Changeset, ChangesetRecord
from deltasherlock.common.fingerprinting import Fingerprint, FingerprintingMethod


class EventLabel(models.Model):
    """
    Used to hold "event" (usually an app installation) labels
    """
    name = models.CharField(max_length=255, primary_key=True)

    def __str__(self):
        return self.name


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

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    status = models.CharField(
        max_length=2, choices=STATUS_CHOICES, default='PN')
    last_updated = models.DateTimeField(auto_now=True)
    client_ip = models.GenericIPAddressField(
        verbose_name="Submitting Client IP")
    submission_time = models.DateTimeField(auto_now_add=True)
    endpoint_url = models.URLField()
    parameters = models.CharField(max_length=255, blank=True)
    request_body = models.TextField(verbose_name="Full HTTP Request Text")
    rq_id = models.CharField(max_length=50, verbose_name="RQ Job ID")
    result_labels = models.ManyToManyField(
        EventLabel, verbose_name="Predicted Labels", blank=True)

    def from_request(self, request, rq_id: str) -> int:
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
        self.request_body = "[disabled]"
        self.rq_id = rq_id
        self.save()
        return self.id

    def rq_complete(self, labels: list):
        """
        Called when an RQ worker that's been "dialed in" to Django has completed
        this QueueItem.

        :param labels: the list of predicted labels
        """
        self.status = 'FN'
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
        return str(self.status) + ": " + str(self.id) + " from " + str(self.client_ip) + " at " + str(self.submission_time)


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
        return "CS" + str(self.id) + " labeled " + str(self.labels) + " (P.Qty: " + str(self.predicted_quantity) + ", CT: " + str(self.close_time) + ")"


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
