"""
Unit test for cas-specific authentication details
"""
from unittest import skip

from django.test import TestCase
from django.test.utils import override_settings
from django.contrib.auth.models import User
from django.db import IntegrityError

from xmodule.modulestore.tests.factories import CourseFactory

from student.tests.factories import UserFactory
from student.models import UserProfile, CourseEnrollment
from external_auth.views import cas_create_user
from instructor.enrollment import enroll_email

class CASUserCreatorTest(TestCase):
    def setUp(self):
        self.username =  'test'
        self.attrs = {'mail': 'test@example.com'}

    def tearDown(self):
        User.objects.all().delete()

    def test_create_simple(self):
        cas_create_user(self.username, self.attrs)

        self.assertTrue(
            User.objects.filter(username=self.username, email=self.attrs['mail']).exists()
        )

    @skip('Until user model with unique email restriction')
    def test_repetitive_email(self):
        existing_user = UserFactory.create(email=self.attrs['mail'])
        # TODO: fix when handling this IntegrityError or special exception in cas
        with self.assertRaises(IntegrityError):
            cas_create_user(self.username, self.attrs)


    def test_profile_creation(self):
        attrs = {
            'mail': 'test@example.com',
            'name': 'Test User',
            'nickname': 'Test Nick',
        }
        cas_create_user(self.username, attrs)
        user = User.objects.get(username=self.username)

        self.assertTrue(UserProfile.objects.filter(user=user).exists())
        profile = user.profile
        self.assertEqual(profile.name, attrs['name'])
        self.assertEqual(profile.nickname, attrs['nickname'])

    def test_enroll_pending(self):
        course = CourseFactory.create()
        enroll_email(course.id, self.attrs['mail'], auto_enroll=True)

        cas_create_user(self.username, self.attrs)
        user = User.objects.get(username=self.username)
        self.assertTrue(CourseEnrollment.is_enrolled(user, course.id))
