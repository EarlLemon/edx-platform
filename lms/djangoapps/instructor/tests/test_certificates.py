"""Tests for the certificates panel of the instructor dash. """
import contextlib
import ddt
import mock
import json

from nose.plugins.attrib import attr
from django.core.urlresolvers import reverse
from django.core.exceptions import ObjectDoesNotExist
from django.test.utils import override_settings
from django.conf import settings
from xmodule.modulestore.tests.django_utils import SharedModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory
from config_models.models import cache
from courseware.tests.factories import GlobalStaffFactory, InstructorFactory, UserFactory
from certificates.tests.factories import GeneratedCertificateFactory, CertificateWhitelistFactory
from certificates.models import CertificateGenerationConfiguration, CertificateStatuses, CertificateWhitelist, \
    GeneratedCertificate
from certificates import api as certs_api
from student.models import CourseEnrollment


@attr('shard_1')
@ddt.ddt
class CertificatesInstructorDashTest(SharedModuleStoreTestCase):
    """Tests for the certificate panel of the instructor dash. """

    ERROR_REASON = "An error occurred!"
    DOWNLOAD_URL = "http://www.example.com/abcd123/cert.pdf"

    @classmethod
    def setUpClass(cls):
        super(CertificatesInstructorDashTest, cls).setUpClass()
        cls.course = CourseFactory.create()
        cls.url = reverse(
            'instructor_dashboard',
            kwargs={'course_id': unicode(cls.course.id)}
        )

    def setUp(self):
        super(CertificatesInstructorDashTest, self).setUp()
        self.global_staff = GlobalStaffFactory()
        self.instructor = InstructorFactory(course_key=self.course.id)

        # Need to clear the cache for model-based configuration
        cache.clear()

        # Enable the certificate generation feature
        CertificateGenerationConfiguration.objects.create(enabled=True)

    def test_visible_only_to_global_staff(self):
        # Instructors don't see the certificates section
        self.client.login(username=self.instructor.username, password="test")
        self._assert_certificates_visible(False)

        # Global staff can see the certificates section
        self.client.login(username=self.global_staff.username, password="test")
        self._assert_certificates_visible(True)

    def test_visible_only_when_feature_flag_enabled(self):
        # Disable the feature flag
        CertificateGenerationConfiguration.objects.create(enabled=False)
        cache.clear()

        # Now even global staff can't see the certificates section
        self.client.login(username=self.global_staff.username, password="test")
        self._assert_certificates_visible(False)

    @ddt.data("started", "error", "success")
    def test_show_certificate_status(self, status):
        self.client.login(username=self.global_staff.username, password="test")
        with self._certificate_status("honor", status):
            self._assert_certificate_status("honor", status)

    def test_show_enabled_button(self):
        self.client.login(username=self.global_staff.username, password="test")

        # Initially, no example certs are generated, so
        # the enable button should be disabled
        self._assert_enable_certs_button_is_disabled()

        with self._certificate_status("honor", "success"):
            # Certs are disabled for the course, so the enable button should be shown
            self._assert_enable_certs_button(True)

            # Enable certificates for the course
            certs_api.set_cert_generation_enabled(self.course.id, True)

            # Now the "disable" button should be shown
            self._assert_enable_certs_button(False)

    def test_can_disable_even_after_failure(self):
        self.client.login(username=self.global_staff.username, password="test")

        with self._certificate_status("honor", "error"):
            # When certs are disabled for a course, then don't allow them
            # to be enabled if certificate generation doesn't complete successfully
            certs_api.set_cert_generation_enabled(self.course.id, False)
            self._assert_enable_certs_button_is_disabled()

            # However, if certificates are already enabled, allow them
            # to be disabled even if an error has occurred
            certs_api.set_cert_generation_enabled(self.course.id, True)
            self._assert_enable_certs_button(False)

    @mock.patch.dict(settings.FEATURES, {'CERTIFICATES_HTML_VIEW': True})
    def test_show_enabled_button_for_html_certs(self):
        """
        Tests `Enable Student-Generated Certificates` button is enabled
        and `Generate Example Certificates` button is not available if
        course has Web/HTML certificates view enabled.
        """
        self.course.cert_html_view_enabled = True
        self.course.save()
        self.store.update_item(self.course, self.global_staff.id)  # pylint: disable=no-member
        self.client.login(username=self.global_staff.username, password="test")
        response = self.client.get(self.url)
        self.assertContains(response, 'Enable Student-Generated Certificates')
        self.assertContains(response, 'enable-certificates-submit')
        self.assertNotContains(response, 'Generate Example Certificates')

    @mock.patch.dict(settings.FEATURES, {'CERTIFICATES_HTML_VIEW': True})
    def test_buttons_for_html_certs_in_self_paced_course(self):
        """
        Tests `Enable Student-Generated Certificates` button is enabled
        and `Generate Certificates` button is not available if
        course has Web/HTML certificates view enabled on a self paced course.
        """
        self.course.cert_html_view_enabled = True
        self.course.save()
        self.store.update_item(self.course, self.global_staff.id)  # pylint: disable=no-member
        self.client.login(username=self.global_staff.username, password="test")
        response = self.client.get(self.url)
        self.assertContains(response, 'Enable Student-Generated Certificates')
        self.assertContains(response, 'enable-certificates-submit')
        self.assertNotContains(response, 'Generate Certificates')
        self.assertNotContains(response, 'btn-start-generating-certificates')

    def _assert_certificates_visible(self, is_visible):
        """Check that the certificates section is visible on the instructor dash. """
        response = self.client.get(self.url)
        if is_visible:
            self.assertContains(response, "Student-Generated Certificates")
        else:
            self.assertNotContains(response, "Student-Generated Certificates")

    @contextlib.contextmanager
    def _certificate_status(self, description, status):
        """Configure the certificate status by mocking the certificates API. """
        patched = 'instructor.views.instructor_dashboard.certs_api.example_certificates_status'
        with mock.patch(patched) as certs_api_status:
            cert_status = [{
                'description': description,
                'status': status
            }]

            if status == 'error':
                cert_status[0]['error_reason'] = self.ERROR_REASON
            if status == 'success':
                cert_status[0]['download_url'] = self.DOWNLOAD_URL

            certs_api_status.return_value = cert_status
            yield

    def _assert_certificate_status(self, cert_name, expected_status):
        """Check the certificate status display on the instructor dash. """
        response = self.client.get(self.url)

        if expected_status == 'started':
            expected = 'Generating example {name} certificate'.format(name=cert_name)
            self.assertContains(response, expected)
        elif expected_status == 'error':
            expected = self.ERROR_REASON
            self.assertContains(response, expected)
        elif expected_status == 'success':
            expected = self.DOWNLOAD_URL
            self.assertContains(response, expected)
        else:
            self.fail("Invalid certificate status: {status}".format(status=expected_status))

    def _assert_enable_certs_button_is_disabled(self):
        """Check that the "enable student-generated certificates" button is disabled. """
        response = self.client.get(self.url)
        expected_html = '<button class="is-disabled" disabled>Enable Student-Generated Certificates</button>'
        self.assertContains(response, expected_html)

    def _assert_enable_certs_button(self, is_enabled):
        """Check whether the button says "enable" or "disable" cert generation. """
        response = self.client.get(self.url)
        expected_html = (
            'Enable Student-Generated Certificates' if is_enabled
            else 'Disable Student-Generated Certificates'
        )
        self.assertContains(response, expected_html)


@attr('shard_1')
@override_settings(CERT_QUEUE='certificates')
@ddt.ddt
class CertificatesInstructorApiTest(SharedModuleStoreTestCase):
    """Tests for the certificates end-points in the instructor dash API. """
    @classmethod
    def setUpClass(cls):
        super(CertificatesInstructorApiTest, cls).setUpClass()
        cls.course = CourseFactory.create()

    def setUp(self):
        super(CertificatesInstructorApiTest, self).setUp()
        self.global_staff = GlobalStaffFactory()
        self.instructor = InstructorFactory(course_key=self.course.id)
        self.user = UserFactory()
        CourseEnrollment.enroll(self.user, self.course.id)

        # Enable certificate generation
        cache.clear()
        CertificateGenerationConfiguration.objects.create(enabled=True)

    @ddt.data('generate_example_certificates', 'enable_certificate_generation')
    def test_allow_only_global_staff(self, url_name):
        url = reverse(url_name, kwargs={'course_id': self.course.id})

        # Instructors do not have access
        self.client.login(username=self.instructor.username, password='test')
        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)

        # Global staff have access
        self.client.login(username=self.global_staff.username, password='test')
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

    def test_generate_example_certificates(self):
        self.client.login(username=self.global_staff.username, password='test')
        url = reverse(
            'generate_example_certificates',
            kwargs={'course_id': unicode(self.course.id)}
        )
        response = self.client.post(url)

        # Expect a redirect back to the instructor dashboard
        self._assert_redirects_to_instructor_dash(response)

        # Expect that certificate generation started
        # Cert generation will fail here because XQueue isn't configured,
        # but the status should at least not be None.
        status = certs_api.example_certificates_status(self.course.id)
        self.assertIsNot(status, None)

    @ddt.data(True, False)
    def test_enable_certificate_generation(self, is_enabled):
        self.client.login(username=self.global_staff.username, password='test')
        url = reverse(
            'enable_certificate_generation',
            kwargs={'course_id': unicode(self.course.id)}
        )
        params = {'certificates-enabled': 'true' if is_enabled else 'false'}
        response = self.client.post(url, data=params)

        # Expect a redirect back to the instructor dashboard
        self._assert_redirects_to_instructor_dash(response)

        # Expect that certificate generation is now enabled for the course
        actual_enabled = certs_api.cert_generation_enabled(self.course.id)
        self.assertEqual(is_enabled, actual_enabled)

    def _assert_redirects_to_instructor_dash(self, response):
        """Check that the response redirects to the certificates section. """
        expected_redirect = reverse(
            'instructor_dashboard',
            kwargs={'course_id': unicode(self.course.id)}
        )
        expected_redirect += '#view-certificates'
        self.assertRedirects(response, expected_redirect)

    def test_certificate_generation_api_without_global_staff(self):
        """
        Test certificates generation api endpoint returns permission denied if
        user who made the request is not member of global staff.
        """
        user = UserFactory.create()
        self.client.login(username=user.username, password='test')
        url = reverse(
            'start_certificate_generation',
            kwargs={'course_id': unicode(self.course.id)}
        )

        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)

        self.client.login(username=self.instructor.username, password='test')
        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)

    def test_certificate_generation_api_with_global_staff(self):
        """
        Test certificates generation api endpoint returns success status when called with
        valid course key
        """
        self.client.login(username=self.global_staff.username, password='test')
        url = reverse(
            'start_certificate_generation',
            kwargs={'course_id': unicode(self.course.id)}
        )

        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        res_json = json.loads(response.content)
        self.assertIsNotNone(res_json['message'])
        self.assertIsNotNone(res_json['task_id'])



@attr('shard_1')
@override_settings(CERT_QUEUE='certificates')
@ddt.ddt
class CertificateExceptionViewInstructorApiTest(SharedModuleStoreTestCase):
    """Tests for the generate certificates end-points in the instructor dash API. """
    @classmethod
    def setUpClass(cls):
        super(CertificateExceptionViewInstructorApiTest, cls).setUpClass()
        cls.course = CourseFactory.create()

    def setUp(self):
        super(CertificateExceptionViewInstructorApiTest, self).setUp()
        self.global_staff = GlobalStaffFactory()
        self.instructor = InstructorFactory(course_key=self.course.id)
        self.user = UserFactory()
        self.user2 = UserFactory()
        CourseEnrollment.enroll(self.user, self.course.id)
        CourseEnrollment.enroll(self.user2, self.course.id)
        self.url = reverse('certificate_exception_view', kwargs={'course_id': unicode(self.course.id)})

        certificate_white_list_item = CertificateWhitelistFactory.create(
            user=self.user2,
            course_id=self.course.id,
        )

        self.certificate_exception = dict(
            created="",
            notes="Test Notes for Test Certificate Exception",
            user_email='',
            user_id='',
            user_name=unicode(self.user.username)
        )

        self.certificate_exception_in_db = dict(
            id=certificate_white_list_item.id,
            user_name=certificate_white_list_item.user.username,
            notes=certificate_white_list_item.notes,
            user_email=certificate_white_list_item.user.email,
            user_id=certificate_white_list_item.user.id,
        )

        # Enable certificate generation
        cache.clear()
        CertificateGenerationConfiguration.objects.create(enabled=True)
        self.client.login(username=self.global_staff.username, password='test')

    def test_certificate_exception_added_successfully(self):
        """
        Test certificates exception addition api endpoint returns success status and updated certificate exception data
        when called with valid course key and certificate exception data
        """
        response = self.client.post(
            self.url,
            data=json.dumps(self.certificate_exception),
            content_type='application/json'
        )
        # Assert successful request processing
        self.assertEqual(response.status_code, 200)
        certificate_exception = json.loads(response.content)

        # Assert Certificate Exception Updated data
        self.assertEqual(certificate_exception['user_email'], self.user.email)
        self.assertEqual(certificate_exception['user_name'], self.user.username)
        self.assertEqual(certificate_exception['user_id'], self.user.id)  # pylint: disable=no-member

    def test_certificate_exception_invalid_username_error(self):
        """
        Test certificates exception addition api endpoint returns failure when called with
        invalid username.
        """
        invalid_user = 'test_invalid_user_name'
        self.certificate_exception.update({'user_name': invalid_user})
        response = self.client.post(
            self.url,
            data=json.dumps(self.certificate_exception),
            content_type='application/json'
        )

        # Assert 400 status code in response
        self.assertEqual(response.status_code, 400)
        res_json = json.loads(response.content)

        # Assert Request not successful
        self.assertFalse(res_json['success'])

        # Assert Error Message
        self.assertEqual(
            res_json['message'],
            u'Student (username/email={user}) does not exist'.format(user=invalid_user)
        )

    def test_certificate_exception_missing_username_and_email_error(self):
        """
        Test certificates exception addition api endpoint returns failure when called with
        missing username/email.
        """
        self.certificate_exception.update({'user_name': '', 'user_email': ''})
        response = self.client.post(
            self.url,
            data=json.dumps(self.certificate_exception),
            content_type='application/json'
        )

        # Assert 400 status code in response
        self.assertEqual(response.status_code, 400)
        res_json = json.loads(response.content)

        # Assert Request not successful
        self.assertFalse(res_json['success'])

        # Assert Error Message
        self.assertEqual(
            res_json['message'],
            u'Student username/email is required.'
        )

    def test_certificate_exception_duplicate_user_error(self):
        """
        Test certificates exception addition api endpoint returns failure when called with
        username/email that already exists in 'CertificateWhitelist' table.
        """
        response = self.client.post(
            self.url,
            data=json.dumps(self.certificate_exception_in_db),
            content_type='application/json'
        )

        # Assert 400 status code in response
        self.assertEqual(response.status_code, 400)
        res_json = json.loads(response.content)

        # Assert Request not successful
        self.assertFalse(res_json['success'])

        user = self.certificate_exception_in_db['user_name']
        # Assert Error Message
        self.assertEqual(
            res_json['message'],
            u"Student (username/email={user_name}) already in certificate exception list.".format(user_name=user)
        )

    def test_certificate_exception_same_user_in_two_different_courses(self):
        """
        Test certificates exception addition api endpoint in scenario when same
        student is added to two different courses.
        """
        response = self.client.post(
            self.url,
            data=json.dumps(self.certificate_exception),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        certificate_exception = json.loads(response.content)

        # Assert Certificate Exception Updated data
        self.assertEqual(certificate_exception['user_email'], self.user.email)
        self.assertEqual(certificate_exception['user_name'], self.user.username)
        self.assertEqual(certificate_exception['user_id'], self.user.id)  # pylint: disable=no-member

        course2 = CourseFactory.create()
        url_course2 = reverse(
            'certificate_exception_view',
            kwargs={'course_id': unicode(course2.id)}
        )

        # add certificate exception for same user in a different course
        self.client.post(
            url_course2,
            data=json.dumps(self.certificate_exception),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        certificate_exception = json.loads(response.content)

        # Assert Certificate Exception Updated data
        self.assertEqual(certificate_exception['user_email'], self.user.email)
        self.assertEqual(certificate_exception['user_name'], self.user.username)
        self.assertEqual(certificate_exception['user_id'], self.user.id)  # pylint: disable=no-member

    def test_certificate_exception_removed_successfully(self):
        """
        Test certificates exception removal api endpoint returns success status
        when called with valid course key and certificate exception id
        """
        GeneratedCertificateFactory.create(
            user=self.user2,
            course_id=self.course.id,
            status=CertificateStatuses.downloadable,
            grade='1.0'
        )
        response = self.client.post(
            self.url,
            data=json.dumps(self.certificate_exception_in_db),
            content_type='application/json',
            REQUEST_METHOD='DELETE'
        )
        # Assert successful request processing
        self.assertEqual(response.status_code, 204)

        # Verify that certificate exception successfully removed from CertificateWhitelist and GeneratedCertificate
        with self.assertRaises(ObjectDoesNotExist):
            CertificateWhitelist.objects.get(user=self.user2, course_id=self.course.id)
            GeneratedCertificate.objects.get(
                user=self.user2, course_id=self.course.id, status__not=CertificateStatuses.unavailable
            )

    def test_remove_certificate_exception_invalid_request_error(self):
        """
        Test certificates exception removal api endpoint returns error
        when called without certificate exception id
        """
        # Try to delete certificate exception without passing valid data
        response = self.client.post(
            self.url,
            data='Test Invalid data',
            content_type='application/json',
            REQUEST_METHOD='DELETE'
        )
        # Assert error on request
        self.assertEqual(response.status_code, 400)

        res_json = json.loads(response.content)

        # Assert Request not successful
        self.assertFalse(res_json['success'])
        # Assert Error Message
        self.assertEqual(
            res_json['message'],
            u"Invalid Json data"
        )

    def test_remove_certificate_exception_non_existing_error(self):
        """
        Test certificates exception removal api endpoint returns error
        when called with non existing certificate exception id
        """
        response = self.client.post(
            self.url,
            data=json.dumps(self.certificate_exception),
            content_type='application/json',
            REQUEST_METHOD='DELETE'
        )
        # Assert error on request
        self.assertEqual(response.status_code, 400)

        res_json = json.loads(response.content)

        # Assert Request not successful
        self.assertFalse(res_json['success'])
        # Assert Error Message
        self.assertEqual(
            res_json['message'],
            u"Certificate exception [user={}] does not exist in "
            u"certificate white list.".format(self.certificate_exception['user_name'])
        )


@attr('shard_1')
@override_settings(CERT_QUEUE='certificates')
@ddt.ddt
class GenerateCertificatesInstructorApiTest(SharedModuleStoreTestCase):
    """Tests for the generate certificates end-points in the instructor dash API. """
    @classmethod
    def setUpClass(cls):
        super(GenerateCertificatesInstructorApiTest, cls).setUpClass()
        cls.course = CourseFactory.create()

    def setUp(self):
        super(GenerateCertificatesInstructorApiTest, self).setUp()
        self.global_staff = GlobalStaffFactory()
        self.instructor = InstructorFactory(course_key=self.course.id)
        self.user = UserFactory()
        CourseEnrollment.enroll(self.user, self.course.id)
        certificate_exception = CertificateWhitelistFactory.create(
            user=self.user,
            course_id=self.course.id,
        )

        self.certificate_exception = dict(
            id=certificate_exception.id,
            user_name=certificate_exception.user.username,
            notes=certificate_exception.notes,
            user_email=certificate_exception.user.email,
            user_id=certificate_exception.user.id,
        )

        # Enable certificate generation
        cache.clear()
        CertificateGenerationConfiguration.objects.create(enabled=True)
        self.client.login(username=self.global_staff.username, password='test')

    def test_generate_certificate_exceptions_all_students(self):
        """
        Test generate certificates exceptions api endpoint returns success
        when called with existing certificate exception
        """
        url = reverse(
            'generate_certificate_exceptions',
            kwargs={'course_id': unicode(self.course.id), 'generate_for': 'all'}
        )

        response = self.client.post(
            url,
            data=json.dumps([self.certificate_exception]),
            content_type='application/json'
        )
        # Assert Success
        self.assertEqual(response.status_code, 200)

        res_json = json.loads(response.content)

        # Assert Request is successful
        self.assertTrue(res_json['success'])
        # Assert Message
        self.assertEqual(
            res_json['message'],
            u"Certificate generation started for white listed students."
        )

    def test_generate_certificate_exceptions_invalid_user_list_error(self):
        """
        Test generate certificates exceptions api endpoint returns error
        when called with certificate exceptions with empty 'user_id' field
        """
        url = reverse(
            'generate_certificate_exceptions',
            kwargs={'course_id': unicode(self.course.id), 'generate_for': 'new'}
        )

        # assign empty user_id
        self.certificate_exception.update({'user_id': ''})

        response = self.client.post(
            url,
            data=json.dumps([self.certificate_exception]),
            content_type='application/json'
        )
        # Assert Failure
        self.assertEqual(response.status_code, 400)

        res_json = json.loads(response.content)

        # Assert Request is not successful
        self.assertFalse(res_json['success'])
        # Assert Message
        self.assertEqual(
            res_json['message'],
            u"Invalid data, user_id must be present for all certificate exceptions."
        )
