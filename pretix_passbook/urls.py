from django.urls import path

from .views import PassbookSaveAllView, PassbookSaveView

event_patterns = [
    path(
        "apple-wallet/<str:order>/<str:secret>/all/",
        PassbookSaveAllView.as_view(),
        name="save_all",
    ),
    path(
        "apple-wallet/<str:order>/<str:secret>/<int:position>/",
        PassbookSaveView.as_view(),
        name="save",
    ),
]
