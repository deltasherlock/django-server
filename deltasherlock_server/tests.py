"""
Test cases for DeltaSherlock's django-server component. For information on
running these tests, see
https://docs.djangoproject.com/en/1.10/topics/testing/overview/#running-tests
"""
import time
import random as rand
from django.test import TestCase
from deltasherlock_server import models as m
import deltasherlock.common.io as io
from deltasherlock.common.changesets import Changeset
from deltasherlock.common.fingerprinting import FingerprintingMethod, Fingerprint


class EventLabelTestCase(TestCase):
    """
    Simple test cases for our simplest model. Use this class as an example when
    writing other tests
    """

    def setUp(self):
        self.NUM_LABELS = 50
        self.PREFIX = "test_label_"
        for i in range(self.NUM_LABELS):
            m.EventLabel.objects.create(name=self.PREFIX + str(i))

    def test_verify_creation(self):
        """
        Simple to test to verify EventLabels are created correctly
        """
        for i in range(self.NUM_LABELS):
            label = m.EventLabel.objects.get(name=self.PREFIX + str(i))
            self.assertEqual(label.name, self.PREFIX + str(i))

    def tearDown(self):
        for i in range(self.NUM_LABELS):
            m.EventLabel.objects.get(name=self.PREFIX + str(i)).delete()


class ChangesetWrapperTestCase(TestCase):

    def setUp(self):
        self.NUM_CHANGESETS = 50
        self.changesets = []

        # Manufacture some raw changesets
        for i in range(self.NUM_CHANGESETS):
            ot = int(time.time()) - 30
            c = Changeset(open_time=ot)
            for i in range(rand.randint(30, 300)):
                c.add_creation_record(
                    filename="/test/created/" + io.uid(), mtime=ot + rand.randint(1, 59))
            for i in range(rand.randint(30, 300)):
                c.add_modification_record(
                    filename="/test/modified/" + io.uid(), mtime=ot + rand.randint(1, 59))
            for i in range(rand.randint(30, 300)):
                c.add_deletion_record(
                    filename="/test/deleted/" + io.uid(), mtime=ot + rand.randint(1, 59))

            c.close(ot + 60)
            self.changesets.append(c)

    def test_wrap_changeset(self):
        for changeset in self.changesets:
            cw = m.ChangesetWrapper()
            cw.wrap(changeset)
            # Test a few attributes for sanity
            self.assertEqual(cw.predicted_quantity,
                             changeset.predicted_quantity)

    def test_unwrap_changeset(self):
        for changeset in self.changesets:
            cw = m.ChangesetWrapper()
            cw.wrap(changeset)
            unwrapped = cw.unwrap()
            # Test for total equality
            self.assertEqual(unwrapped, changeset)

    def tearDown(self):
        m.ChangesetWrapper.objects.all().delete()
