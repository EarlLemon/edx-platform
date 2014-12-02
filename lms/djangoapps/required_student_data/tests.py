"""
Tests for required student data form
"""
import json
import datetime
from time import sleep

from django.test import TestCase
from django.test.client import Client
from django.test.utils import override_settings
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse

from xmodule.modulestore.tests.factories import CourseFactory

from student.tests.factories import UserFactory, UserProfileFactory
from student.roles import CourseStaffRole

@override_settings(REQUIRE_STUDENT_DATA_FOR_COURSEWARE=True)
class RequiredStudentDataTest(TestCase):
    """
    Tests for required student data form
    """
    @classmethod
    def setUpClass(cls):
        cls.course = CourseFactory.create()
        cls.postpone_url = reverse('postpone_required_data_update')
        cls.update_url = reverse('update_required_data')
        cls.data = {
            'first_name': 'test',
            'last_name': 'test',
            'birthdate': '2014-07-28',
        }

    def setUp(self):
        self.user = UserFactory.create(password='test')
        profile = UserProfileFactory.create(
            user=self.user,
            first_name='',
            last_name='',
            birthdate=None
        )
        self.client = Client()
        self.client.login(username=self.user.username, password='test')

    def tearDown(self):
        self.client.logout()
        User.objects.all().delete()

    def test_form_rendered(self):
        '''Test whether form appears for user having no required information'''
        self.assertTrue(self._form_appears())

    def test_postpone(self):
        '''Test whether form does not appear after postpone action'''
        self.client.post(self.postpone_url)
        self.assertFalse(self._form_appears())

    @override_settings(USER_DATA_REQUEST_TIMEOUT=datetime.timedelta(seconds=1))
    def test_postpone_awake(self):
        '''Test whether form appears again after postpone period'''
        self.client.post(self.postpone_url)
        self.assertFalse(self._form_appears())
        sleep(2)
        self.assertTrue(self._form_appears())

    def test_update_all_required_fields(self):
        '''Test whether form does not appear after complete update action'''
        self.client.post(self.update_url, self.data)
        self.assertFalse(self._form_appears())

    def test_updated_fields(self):
        '''Test form fields are saved correctly'''
        self.client.post(self.update_url, self.data)
        profile = self.user.profile
        self.assertEqual(profile.first_name, self.data['first_name'])
        self.assertEqual(profile.last_name, self.data['last_name'])
        self.assertEqual(
            profile.birthdate and profile.birthdate.strftime('%Y-%m-%d'),
            self.data['birthdate']
        )

    @override_settings(USER_DATA_REQUEST_TIMEOUT=datetime.timedelta(seconds=1))
    def test_skip_last_name(self):
        data = self.data.copy()
        data['last_name'] = ''
        response = self.client.post(self.update_url, data)
        sleep(2)
        self.assertFalse(self._form_appears())

    def test_invalid_birthdate(self):
        '''Test wheter response with errors list is returned on invalid birthdate'''
        data = self.data.copy()
        data['birthdate'] = 'invalid'
        response = self.client.post(self.update_url, data)

        self.assertIn('errors', response.content)
        self.assertIn('birthdate', response.content)

    @override_settings(USER_DATA_REQUEST_TIMEOUT=datetime.timedelta(seconds=1))
    def test_partial_update_postponed(self):
        '''Test wheter partial update is processed but request is fired again'''
        data = self.data.copy()
        data['birthdate'] = ''
        response = self.client.post(self.update_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self._form_appears())
        sleep(2)
        self.assertTrue(self._form_appears())

    @override_settings(USER_DATA_REQUEST_TIMEOUT=datetime.timedelta(seconds=1))
    def test_request_after_data_removal(self):
        '''Test repetitive request after data removal'''
        response = self.client.post(self.update_url, self.data)
        sleep(2)
        self.assertFalse(self._form_appears())

        profile = self.user.profile
        profile.birthdate = None
        profile.save()
        self.assertTrue(self._form_appears())

    def test_course_staff_skipped(self):
        CourseStaffRole(self.course.id).add_users(self.user)
        self.assertFalse(self._form_appears())

    def test_global_staff_skipped(self):
        self.user.is_staff = True
        self.user.save()
        self.assertFalse(self._form_appears())

    def _form_appears(self):
        url = reverse('info', args=[self.course.id.to_deprecated_string()])
        response = self.client.get(url)
        return 'required_student_data_form' in response.content
