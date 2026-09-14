"""Production media is authorized by Django, never a public directory alias."""

from django.urls import path
from config.urls import urlpatterns as project_urls
from config.beta_media import media_file

urlpatterns = [path('media/<path:name>', media_file, name='beta_media')] + project_urls
