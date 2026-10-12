from django.contrib import admin

from tracker.models import DomainRule, PriceChange, Product

admin.site.register([DomainRule, Product, PriceChange])
