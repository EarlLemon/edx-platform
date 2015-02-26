'''
Tests for student activation and login
'''
import json
import unittest

from django.test import TestCase
from django.test.client import Client
from django.test.utils import override_settings
from django.conf import settings
from django.core.cache import cache
from django.core.urlresolvers import reverse, NoReverseMatch
from django.http import HttpResponseBadRequest, HttpResponse
from external_auth.models import ExternalAuthMap
import httpretty
from mock import patch
from opaque_keys.edx.locations import SlashSeparatedCourseKey
from social.apps.django_app.default.models import UserSocialAuth

from xmodule.modulestore.tests.django_utils import TEST_DATA_MOCK_MODULESTORE
from student.tests.factories import UserFactory, RegistrationFactory, UserProfileFactory
from student.views import (
    _parse_course_id_from_string,
    _get_course_enrollment_domain,
    login_oauth_token,
)
from xmodule.modulestore.tests.factories import CourseFactory
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase


class LoginTest(TestCase):
    '''
    Test student.views.login_user() view
    '''

    def setUp(self):
        # Create one user and save it to the database
        self.user = UserFactory.build(username='test', email='test@edx.org')
        self.user.set_password('test_password')
        self.user.save()

        # Create a registration for the user
        RegistrationFactory(user=self.user)

        # Create a profile for the user
        UserProfileFactory(user=self.user)

        # Create the test client
        self.client = Client()
        cache.clear()

        # Store the login url
        try:
            self.url = reverse('login_post')
        except NoReverseMatch:
            self.url = reverse('login')

    def test_login_success(self):
        response, mock_audit_log = self._login_response('test@edx.org', 'test_password', patched_audit_log='student.models.AUDIT_LOG')
        self._assert_response(response, success=True)
        self._assert_audit_log(mock_audit_log, 'info', [u'Login success', u'test@edx.org'])

    @patch.dict("django.conf.settings.FEATURES", {'SQUELCH_PII_IN_LOGS': True})
    def test_login_success_no_pii(self):
        response, mock_audit_log = self._login_response('test@edx.org', 'test_password', patched_audit_log='student.models.AUDIT_LOG')
        self._assert_response(response, success=True)
        self._assert_audit_log(mock_audit_log, 'info', [u'Login success'])
        self._assert_not_in_audit_log(mock_audit_log, 'info', [u'test@edx.org'])

    def test_login_success_unicode_email(self):
        unicode_email = u'test' + unichr(40960) + u'@edx.org'
        self.user.email = unicode_email
        self.user.save()

        response, mock_audit_log = self._login_response(unicode_email, 'test_password', patched_audit_log='student.models.AUDIT_LOG')
        self._assert_response(response, success=True)
        self._assert_audit_log(mock_audit_log, 'info', [u'Login success', unicode_email])

    def test_login_fail_no_user_exists(self):
        nonexistent_email = u'not_a_user@edx.org'
        response, mock_audit_log = self._login_response(nonexistent_email, 'test_password')
        self._assert_response(response, success=False,
                              value='Email or password is incorrect')
        self._assert_audit_log(mock_audit_log, 'warning', [u'Login failed', u'Unknown user email', nonexistent_email])

    @patch.dict("django.conf.settings.FEATURES", {'SQUELCH_PII_IN_LOGS': True})
    def test_login_fail_no_user_exists_no_pii(self):
        nonexistent_email = u'not_a_user@edx.org'
        response, mock_audit_log = self._login_response(nonexistent_email, 'test_password')
        self._assert_response(response, success=False,
                              value='Email or password is incorrect')
        self._assert_audit_log(mock_audit_log, 'warning', [u'Login failed', u'Unknown user email'])
        self._assert_not_in_audit_log(mock_audit_log, 'warning', [nonexistent_email])

    def test_login_fail_wrong_password(self):
        response, mock_audit_log = self._login_response('test@edx.org', 'wrong_password')
        self._assert_response(response, success=False,
                              value='Email or password is incorrect')
        self._assert_audit_log(mock_audit_log, 'warning', [u'Login failed', u'password for', u'test@edx.org', u'invalid'])

    @patch.dict("django.conf.settings.FEATURES", {'SQUELCH_PII_IN_LOGS': True})
    def test_login_fail_wrong_password_no_pii(self):
        response, mock_audit_log = self._login_response('test@edx.org', 'wrong_password')
        self._assert_response(response, success=False,
                              value='Email or password is incorrect')
        self._assert_audit_log(mock_audit_log, 'warning', [u'Login failed', u'password for', u'invalid'])
        self._assert_not_in_audit_log(mock_audit_log, 'warning', [u'test@edx.org'])

    def test_login_not_activated(self):
        # De-activate the user
        self.user.is_active = False
        self.user.save()

        # Should now be unable to login
        response, mock_audit_log = self._login_response('test@edx.org', 'test_password')
        self._assert_response(response, success=False,
                              value="This account has not been activated")
        self._assert_audit_log(mock_audit_log, 'warning', [u'Login failed', u'Account not active for user'])

    @patch.dict("django.conf.settings.FEATURES", {'SQUELCH_PII_IN_LOGS': True})
    def test_login_not_activated_no_pii(self):
        # De-activate the user
        self.user.is_active = False
        self.user.save()

        # Should now be unable to login
        response, mock_audit_log = self._login_response('test@edx.org', 'test_password')
        self._assert_response(response, success=False,
                              value="This account has not been activated")
        self._assert_audit_log(mock_audit_log, 'warning', [u'Login failed', u'Account not active for user'])
        self._assert_not_in_audit_log(mock_audit_log, 'warning', [u'test'])

    def test_login_unicode_email(self):
        unicode_email = u'test@edx.org' + unichr(40960)
        response, mock_audit_log = self._login_response(unicode_email, 'test_password')
        self._assert_response(response, success=False)
        self._assert_audit_log(mock_audit_log, 'warning', [u'Login failed', unicode_email])

    def test_login_unicode_password(self):
        unicode_password = u'test_password' + unichr(1972)
        response, mock_audit_log = self._login_response('test@edx.org', unicode_password)
        self._assert_response(response, success=False)
        self._assert_audit_log(mock_audit_log, 'warning', [u'Login failed', u'password for', u'test@edx.org', u'invalid'])

    def test_logout_logging(self):
        response, _ = self._login_response('test@edx.org', 'test_password')
        self._assert_response(response, success=True)
        logout_url = reverse('logout')
        with patch('student.models.AUDIT_LOG') as mock_audit_log:
            response = self.client.post(logout_url)
        self.assertEqual(response.status_code, 302)
        self._assert_audit_log(mock_audit_log, 'info', [u'Logout', u'test'])

    @patch.dict("django.conf.settings.FEATURES", {'SQUELCH_PII_IN_LOGS': True})
    def test_logout_logging_no_pii(self):
        response, _ = self._login_response('test@edx.org', 'test_password')
        self._assert_response(response, success=True)
        logout_url = reverse('logout')
        with patch('student.models.AUDIT_LOG') as mock_audit_log:
            response = self.client.post(logout_url)
        self.assertEqual(response.status_code, 302)
        self._assert_audit_log(mock_audit_log, 'info', [u'Logout'])
        self._assert_not_in_audit_log(mock_audit_log, 'info', [u'test'])

    def test_login_ratelimited_success(self):
        # Try (and fail) logging in with fewer attempts than the limit of 30
        # and verify that you can still successfully log in afterwards.
        for i in xrange(20):
            password = u'test_password{0}'.format(i)
            response, _audit_log = self._login_response('test@edx.org', password)
            self._assert_response(response, success=False)
        # now try logging in with a valid password
        response, _audit_log = self._login_response('test@edx.org', 'test_password')
        self._assert_response(response, success=True)

    def test_login_ratelimited(self):
        # try logging in 30 times, the default limit in the number of failed
        # login attempts in one 5 minute period before the rate gets limited
        for i in xrange(30):
            password = u'test_password{0}'.format(i)
            self._login_response('test@edx.org', password)
        # check to see if this response indicates that this was ratelimited
        response, _audit_log = self._login_response('test@edx.org', 'wrong_password')
        self._assert_response(response, success=False, value='Too many failed login attempts')

    @patch.dict("django.conf.settings.FEATURES", {'PREVENT_CONCURRENT_LOGINS': True})
    def test_single_session(self):
        creds = {'email': 'test@edx.org', 'password': 'test_password'}
        client1 = Client()
        client2 = Client()

        response = client1.post(self.url, creds)
        self._assert_response(response, success=True)

        self.assertEqual(self.user.profile.get_meta()['session_id'], client1.session.session_key)

        # second login should log out the first
        response = client2.post(self.url, creds)
        self._assert_response(response, success=True)

        try:
            # this test can be run with either lms or studio settings
            # since studio does not have a dashboard url, we should
            # look for another url that is login_required, in that case
            url = reverse('dashboard')
        except NoReverseMatch:
            url = reverse('upload_transcripts')
        response = client1.get(url)
        # client1 will be logged out
        self.assertEqual(response.status_code, 302)

    @patch.dict("django.conf.settings.FEATURES", {'PREVENT_CONCURRENT_LOGINS': True})
    def test_single_session_with_url_not_having_login_required_decorator(self):
        # accessing logout url as it does not have login-required decorator it will avoid redirect
        # and go inside the enforce_single_login

        creds = {'email': 'test@edx.org', 'password': 'test_password'}
        client1 = Client()
        client2 = Client()

        response = client1.post(self.url, creds)
        self._assert_response(response, success=True)

        self.assertEqual(self.user.profile.get_meta()['session_id'], client1.session.session_key)

        # second login should log out the first
        response = client2.post(self.url, creds)
        self._assert_response(response, success=True)

        url = reverse('logout')

        response = client1.get(url)
        self.assertEqual(response.status_code, 302)

    def test_change_enrollment_400(self):
        """
        Tests that a 400 in change_enrollment doesn't lead to a 404
        and in fact just logs in the user without incident
        """
        # add this post param to trigger a call to change_enrollment
        extra_post_params = {"enrollment_action": "enroll"}
        with patch('student.views.change_enrollment') as mock_change_enrollment:
            mock_change_enrollment.return_value = HttpResponseBadRequest("I am a 400")
            response, _ = self._login_response(
                'test@edx.org',
                'test_password',
                extra_post_params=extra_post_params,
            )
        response_content = json.loads(response.content)
        self.assertIsNone(response_content["redirect_url"])
        self._assert_response(response, success=True)

    def test_change_enrollment_200_no_redirect(self):
        """
        Tests "redirect_url" is None if change_enrollment returns a HttpResponse
        with no content
        """
        # add this post param to trigger a call to change_enrollment
        extra_post_params = {"enrollment_action": "enroll"}
        with patch('student.views.change_enrollment') as mock_change_enrollment:
            mock_change_enrollment.return_value = HttpResponse()
            response, _ = self._login_response(
                'test@edx.org',
                'test_password',
                extra_post_params=extra_post_params,
            )
        response_content = json.loads(response.content)
        self.assertIsNone(response_content["redirect_url"])
        self._assert_response(response, success=True)

    def test_change_enrollment_200_redirect(self):
        """
        Tests that "redirect_url" is the content of the HttpResponse returned
        by change_enrollment, if there is content
        """
        # add this post param to trigger a call to change_enrollment
        extra_post_params = {"enrollment_action": "enroll"}
        with patch('student.views.change_enrollment') as mock_change_enrollment:
            mock_change_enrollment.return_value = HttpResponse("in/nature/there/is/nothing/melancholy")
            response, _ = self._login_response(
                'test@edx.org',
                'test_password',
                extra_post_params=extra_post_params,
            )
        response_content = json.loads(response.content)
        self.assertEqual(response_content["redirect_url"], "in/nature/there/is/nothing/melancholy")
        self._assert_response(response, success=True)

    def _login_response(self, email, password, patched_audit_log='student.views.AUDIT_LOG', extra_post_params=None):
        ''' Post the login info '''
        post_params = {'email': email, 'password': password}
        if extra_post_params is not None:
            post_params.update(extra_post_params)
        with patch(patched_audit_log) as mock_audit_log:
            result = self.client.post(self.url, post_params)
        return result, mock_audit_log

    def _assert_response(self, response, success=None, value=None):
        '''
        Assert that the response had status 200 and returned a valid
        JSON-parseable dict.

        If success is provided, assert that the response had that
        value for 'success' in the JSON dict.

        If value is provided, assert that the response contained that
        value for 'value' in the JSON dict.
        '''
        self.assertEqual(response.status_code, 200)

        try:
            response_dict = json.loads(response.content)
        except ValueError:
            self.fail("Could not parse response content as JSON: %s"
                      % str(response.content))

        if success is not None:
            self.assertEqual(response_dict['success'], success)

        if value is not None:
            msg = ("'%s' did not contain '%s'" %
                   (str(response_dict['value']), str(value)))
            self.assertTrue(value in response_dict['value'], msg)

    def _assert_audit_log(self, mock_audit_log, level, log_strings):
        """
        Check that the audit log has received the expected call as its last call.
        """
        method_calls = mock_audit_log.method_calls
        name, args, _kwargs = method_calls[-1]
        self.assertEquals(name, level)
        self.assertEquals(len(args), 1)
        format_string = args[0]
        for log_string in log_strings:
            self.assertIn(log_string, format_string)

    def _assert_not_in_audit_log(self, mock_audit_log, level, log_strings):
        """
        Check that the audit log has received the expected call as its last call.
        """
        method_calls = mock_audit_log.method_calls
        name, args, _kwargs = method_calls[-1]
        self.assertEquals(name, level)
        self.assertEquals(len(args), 1)
        format_string = args[0]
        for log_string in log_strings:
            self.assertNotIn(log_string, format_string)


class UtilFnTest(TestCase):
    """
    Tests for utility functions in student.views
    """
    def test__parse_course_id_from_string(self):
        """
        Tests the _parse_course_id_from_string util function
        """
        COURSE_ID = u'org/num/run'                                # pylint: disable=invalid-name
        COURSE_URL = u'/courses/{}/otherstuff'.format(COURSE_ID)  # pylint: disable=invalid-name
        NON_COURSE_URL = u'/blahblah'                             # pylint: disable=invalid-name
        self.assertEqual(
            _parse_course_id_from_string(COURSE_URL),
            SlashSeparatedCourseKey.from_deprecated_string(COURSE_ID)
        )
        self.assertIsNone(_parse_course_id_from_string(NON_COURSE_URL))


@override_settings(MODULESTORE=TEST_DATA_MOCK_MODULESTORE)
class ExternalAuthShibTest(ModuleStoreTestCase):
    """
    Tests how login_user() interacts with ExternalAuth, in particular Shib
    """
    def setUp(self):
        super(ExternalAuthShibTest, self).setUp()
        self.course = CourseFactory.create(
            org='Stanford',
            number='456',
            display_name='NO SHIB',
            user_id=self.user.id,
        )
        self.shib_course = CourseFactory.create(
            org='Stanford',
            number='123',
            display_name='Shib Only',
            enrollment_domain='shib:https://idp.stanford.edu/',
            user_id=self.user.id,
        )
        self.user_w_map = UserFactory.create(email='withmap@stanford.edu')
        self.extauth = ExternalAuthMap(external_id='withmap@stanford.edu',
                                       external_email='withmap@stanford.edu',
                                       external_domain='shib:https://idp.stanford.edu/',
                                       external_credentials="",
                                       user=self.user_w_map)
        self.user_w_map.save()
        self.extauth.save()
        self.user_wo_map = UserFactory.create(email='womap@gmail.com')
        self.user_wo_map.save()

    @unittest.skipUnless(settings.FEATURES.get('AUTH_USE_SHIB'), "AUTH_USE_SHIB not set")
    def test_login_page_redirect(self):
        """
        Tests that when a shib user types their email address into the login page, they get redirected
        to the shib login.
        """
        response = self.client.post(reverse('login'), {'email': self.user_w_map.email, 'password': ''})
        self.assertEqual(response.status_code, 200)
        obj = json.loads(response.content)
        self.assertEqual(obj, {
            'success': False,
            'redirect': reverse('shib-login'),
        })

    @unittest.skipUnless(settings.FEATURES.get('AUTH_USE_SHIB'), "AUTH_USE_SHIB not set")
    def test__get_course_enrollment_domain(self):
        """
        Tests the _get_course_enrollment_domain utility function
        """
        self.assertIsNone(_get_course_enrollment_domain(SlashSeparatedCourseKey("I", "DONT", "EXIST")))
        self.assertIsNone(_get_course_enrollment_domain(self.course.id))
        self.assertEqual(self.shib_course.enrollment_domain, _get_course_enrollment_domain(self.shib_course.id))

    @unittest.skipUnless(settings.FEATURES.get('AUTH_USE_SHIB'), "AUTH_USE_SHIB not set")
    def test_login_required_dashboard(self):
        """
        Tests redirects to when @login_required to dashboard, which should always be the normal login,
        since there is no course context
        """
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], 'http://testserver/accounts/login?next=/dashboard')

    @unittest.skipUnless(settings.FEATURES.get('AUTH_USE_SHIB'), "AUTH_USE_SHIB not set")
    def test_externalauth_login_required_course_context(self):
        """
        Tests the redirects when visiting course-specific URL with @login_required.
        Should vary by course depending on its enrollment_domain
        """
        TARGET_URL = reverse('courseware', args=[self.course.id.to_deprecated_string()])            # pylint: disable=invalid-name
        noshib_response = self.client.get(TARGET_URL, follow=True)
        self.assertEqual(noshib_response.redirect_chain[-1],
                         ('http://testserver/accounts/login?next={url}'.format(url=TARGET_URL), 302))
        self.assertContains(noshib_response, ("Log into your {platform_name} Account | {platform_name}"
                                              .format(platform_name=settings.PLATFORM_NAME)))
        self.assertEqual(noshib_response.status_code, 200)

        TARGET_URL_SHIB = reverse('courseware', args=[self.shib_course.id.to_deprecated_string()])  # pylint: disable=invalid-name
        shib_response = self.client.get(**{'path': TARGET_URL_SHIB,
                                           'follow': True,
                                           'REMOTE_USER': self.extauth.external_id,
                                           'Shib-Identity-Provider': 'https://idp.stanford.edu/'})
        # Test that the shib-login redirect page with ?next= and the desired page are part of the redirect chain
        # The 'courseware' page actually causes a redirect itself, so it's not the end of the chain and we
        # won't test its contents
        self.assertEqual(shib_response.redirect_chain[-3],
                         ('http://testserver/shib-login/?next={url}'.format(url=TARGET_URL_SHIB), 302))
        self.assertEqual(shib_response.redirect_chain[-2],
                         ('http://testserver{url}'.format(url=TARGET_URL_SHIB), 302))
        self.assertEqual(shib_response.status_code, 200)


@httpretty.activate
class LoginOAuthTokenMixin(object):
    """
    Mixin with tests for the login_oauth_token view. A TestCase that includes
    this must define the following:

    BACKEND: The name of the backend from python-social-auth
    USER_URL: The URL of the endpoint that the backend retrieves user data from
    UID_FIELD: The field in the user data that the backend uses as the user id
    """

    def setUp(self):
        self.client = Client()
        self.url = reverse(login_oauth_token, kwargs={"backend": self.BACKEND})
        self.social_uid = "social_uid"
        self.user = UserFactory()
        UserSocialAuth.objects.create(user=self.user, provider=self.BACKEND, uid=self.social_uid)

    def _setup_user_response(self, success):
        """
        Register a mock response for the third party user information endpoint;
        success indicates whether the response status code should be 200 or 400
        """
        if success:
            status = 200
            body = json.dumps({self.UID_FIELD: self.social_uid})
        else:
            status = 400
            body = json.dumps({})
        httpretty.register_uri(
            httpretty.GET,
            self.USER_URL,
            body=body,
            status=status,
            content_type="application/json"
        )

    def _assert_error(self, response, status_code, error):
        """Assert that the given response was a 400 with the given error code"""
        self.assertEqual(response.status_code, status_code)
        self.assertEqual(json.loads(response.content), {"error": error})
        self.assertNotIn("partial_pipeline", self.client.session)

    def test_success(self):
        self._setup_user_response(success=True)
        response = self.client.post(self.url, {"access_token": "dummy"})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.client.session['_auth_user_id'], self.user.id)  # pylint: disable=no-member

    def test_invalid_token(self):
        self._setup_user_response(success=False)
        response = self.client.post(self.url, {"access_token": "dummy"})
        self._assert_error(response, 401, "invalid_token")

    def test_missing_token(self):
        response = self.client.post(self.url)
        self._assert_error(response, 400, "invalid_request")

    def test_unlinked_user(self):
        UserSocialAuth.objects.all().delete()
        self._setup_user_response(success=True)
        response = self.client.post(self.url, {"access_token": "dummy"})
        self._assert_error(response, 401, "invalid_token")

    def test_get_method(self):
        response = self.client.get(self.url, {"access_token": "dummy"})
        self.assertEqual(response.status_code, 405)


# This is necessary because cms does not implement third party auth
@unittest.skipUnless(settings.FEATURES.get("ENABLE_THIRD_PARTY_AUTH"), "third party auth not enabled")
class LoginOAuthTokenTestFacebook(LoginOAuthTokenMixin, TestCase):
    """Tests login_oauth_token with the Facebook backend"""
    BACKEND = "facebook"
    USER_URL = "https://graph.facebook.com/me"
    UID_FIELD = "id"


# This is necessary because cms does not implement third party auth
@unittest.skipUnless(settings.FEATURES.get("ENABLE_THIRD_PARTY_AUTH"), "third party auth not enabled")
class LoginOAuthTokenTestGoogle(LoginOAuthTokenMixin, TestCase):
    """Tests login_oauth_token with the Google backend"""
    BACKEND = "google-oauth2"
    USER_URL = "https://www.googleapis.com/oauth2/v1/userinfo"
    UID_FIELD = "email"
