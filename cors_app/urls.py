from django.urls import path
from .views import StacovJsonView

urlpatterns = [
    path('api/json/', StacovJsonView.as_view(), name='stacov-json'),
]
