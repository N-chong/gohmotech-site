from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views
from .report_data import REPORTS

# API Router
router = DefaultRouter()
router.register(r'reports', views.ReportViewSet, basename='report')

app_name = 'analytics'

urlpatterns = [
    # API endpoints
    path('api/', include(router.urls)),

    # Report Center (landing page)
    path('', views.report_center_view, name='dashboard'),
    path('farm-report/print/', views.farm_report_print_view, name='farm_report_print'),
]

# One set of routes per report type, generated from the registry so the URL
# names always match REPORTS[...]["url_name"] (e.g. analytics:report_inventory).
for _key in REPORTS:
    urlpatterns += [
        path(f'{_key}/', views.report_view, {'report_type': _key},
             name=f'report_{_key}'),
        path(f'{_key}/print/', views.report_print_view, {'report_type': _key},
             name=f'report_{_key}_print'),
        path(f'{_key}/export/', views.report_export_view, {'report_type': _key},
             name=f'report_{_key}_export'),
    ]
