"""Production URLs with authenticated media delivery."""

from django.urls import path

from config.beta_media import media_file
from config.urls import urlpatterns as project_urls


urlpatterns = [path("media/<path:name>", media_file, name="production_media")] + project_urls
