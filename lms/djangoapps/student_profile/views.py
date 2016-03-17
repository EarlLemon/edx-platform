""" Views for a student's profile information. """

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django_countries import countries

from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import user_passes_test
from django.http import Http404
from django.views.decorators.http import require_http_methods

from edxmako.shortcuts import render_to_response
from openedx.core.djangoapps.user_api.accounts.api import get_account_settings
from openedx.core.djangoapps.user_api.accounts.serializers import PROFILE_IMAGE_KEY_PREFIX
from openedx.core.djangoapps.user_api.errors import UserNotFound, UserNotAuthorized
from openedx.core.djangoapps.user_api.accounts import ACCOUNT_VISIBILITY_PREF_KEY, ALL_USERS_VISIBILITY
from openedx.core.djangoapps.user_api.preferences.api import get_user_preferences
from openedx.core.djangoapps.course_owners.views import get_accessible_owner_courses
from student.models import User
from microsite_configuration import microsite


@user_passes_test(lambda u: settings.FEATURES['ALLOW_PROFILE_ANONYMOUS_ACCESS'] or u.is_authenticated())
@require_http_methods(['GET'])
def learner_profile(request, username):
    """Render the profile page for the specified username.

    Args:
        request (HttpRequest)
        username (str): username of user whose profile is requested.

    Returns:
        HttpResponse: 200 if the page was sent successfully
        HttpResponse: 302 if not logged in (redirect to login page)
        HttpResponse: 405 if using an unsupported HTTP method
    Raises:
        Http404: 404 if the specified user is not authorized or does not exist

    Example usage:
        GET /account/profile
    """
    try:
        return render_to_response(
            'student_profile/learner_profile.html',
            learner_profile_context(request, username)
        )
    except (UserNotAuthorized, UserNotFound, ObjectDoesNotExist):
        raise Http404


def learner_profile_context(request, profile_username):
    """Context for the learner profile page.

    Args:
        request (object): HttpRequest object.
        profile_username (str): username of user whose profile is requested.

    Returns:
        dict

    Raises:
        ObjectDoesNotExist: the specified profile_username does not exist.
    """
    profile_user = User.objects.get(username=profile_username)
    logged_in_user = request.user

    own_profile = (request.user.username == profile_username)

    account_settings_data = get_account_settings(request, profile_username)

    preferences_data = get_user_preferences(profile_user, profile_username)

    context = {
        'data': {
            'profile_user_id': profile_user.id,
            'default_public_account_fields': settings.ACCOUNT_VISIBILITY_CONFIGURATION['public_fields'],
            'default_visibility': settings.ACCOUNT_VISIBILITY_CONFIGURATION['default_visibility'],
            'accounts_api_url': reverse("accounts_api", kwargs={'username': profile_username}),
            'preferences_api_url': reverse('preferences_api', kwargs={'username': profile_username}),
            'preferences_data': preferences_data,
            'account_settings_data': account_settings_data,
            'profile_image_upload_url': reverse('profile_image_upload', kwargs={'username': profile_username}),
            'profile_image_remove_url': reverse('profile_image_remove', kwargs={'username': profile_username}),
            'profile_image_max_bytes': settings.PROFILE_IMAGE_MAX_BYTES,
            'profile_image_min_bytes': settings.PROFILE_IMAGE_MIN_BYTES,
            'account_settings_page_url': reverse('account_settings'),
            'has_preferences_access': (request.user.username == profile_username or request.user.is_staff),
            'own_profile': own_profile,
            'country_options': list(countries),
            'language_options': settings.ALL_LANGUAGES,
            'platform_name': microsite.get_value('platform_name', settings.PLATFORM_NAME),
            'owned_courses_data': {
                'paid_courses_available': settings.FEATURES['ENABLE_SHOPPING_CART'],
                'owned_courses': _get_owned_courses(request, profile_user, preferences_data),
            },
        },
        'disable_courseware_js': True,
    }
    return context


def _get_owned_courses(request, owner, preferences):
    """
    Retrieve details of courses owned by particular user.

    Visibility of courses depends on profile preferences and course settings.
    """
    profile_visibility = preferences.get(ACCOUNT_VISIBILITY_PREF_KEY, ALL_USERS_VISIBILITY)
    if profile_visibility != ALL_USERS_VISIBILITY:
        return []

    courses = get_accessible_owner_courses(request, owner)
    return [{
        'course_id': unicode(course.id),
        'display_name': course.display_name,
        'number': course.display_number_with_default,
        'org': course.display_org_with_default,
        'start_datetime_text': course.start_datetime_text(),
        'course_image': course.course_image_url,
        'about_url': reverse('about_course', args=[course.id.to_deprecated_string()])
    } for course in courses]
