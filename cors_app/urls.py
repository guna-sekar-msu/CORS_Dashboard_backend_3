from django.urls import path
from .views import StacovJsonView,home
from .raw_data_views import RawDataView, ObservationProxyView

urlpatterns = [

    path('', home, name='home'),
    path('api/json/', StacovJsonView.as_view(), name='stacov-json'),
    #path('api/raw-data/', RawDataView.as_view(), name='raw-data'),
    path('api/observations/', ObservationProxyView.as_view(), name='observations'),
    path('api/observations', ObservationProxyView.as_view(), name='observations-no-slash'),
]
    