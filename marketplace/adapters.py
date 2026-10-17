"""Authentication redirects shared by password and social sign-in."""

from allauth.account.adapter import DefaultAccountAdapter
from django.urls import reverse

from .auth import default_page_name


class GoHMoTechAccountAdapter(DefaultAccountAdapter):
    def get_login_redirect_url(self, request):
        return reverse(default_page_name(request.user))
