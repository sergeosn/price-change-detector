"""Django URLs. The whole Django app is mounted under /admin by config.asgi,
so the admin site lives at the root of Django's own URL space."""

from django.contrib import admin
from django.urls import path

urlpatterns = [path("", admin.site.urls)]
