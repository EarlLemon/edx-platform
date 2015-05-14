"""
Slightly customized python-social-auth backend for SAML 2.0 support
"""
from social.backends.saml import SAMLIdentityProvider, SAMLAuth


class SAMLAuthBackend(SAMLAuth):  # pylint: disable=abstract-method
    """
    Customized version of SAMLAuth that gets the list of IdPs from third_party_auth's list of
    enabled providers.
    """
    name = "tpa-saml"

    def get_idp(self, idp_name):
        """ Given the name of an IdP, get a SAMLIdentityProvider instance """
        from .provider import Registry  # Import here to avoid circular import
        for provider in Registry.enabled():
            if issubclass(provider.BACKEND_CLASS, SAMLAuth) and provider.IDP["id"] == idp_name:
                return SAMLIdentityProvider(idp_name, **provider.IDP)
        raise KeyError("SAML IdP {} not found.".format(idp_name))

    def setting(self, name, default=None):
        """ Get a setting, from SAMLConfiguration """
        if not hasattr(self, '_config'):
            from .models import SAMLConfiguration
            self._config = SAMLConfiguration.current()  # pylint: disable=attribute-defined-outside-init
        if not self._config.enabled:
            from django.core.exceptions import ImproperlyConfigured
            raise ImproperlyConfigured("SAML Authentication is not enabled.")
        try:
            return self._config.get_setting(name)
        except KeyError:
            return self.strategy.setting(name, default)
