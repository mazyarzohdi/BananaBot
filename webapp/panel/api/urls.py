from django.urls import path
from . import views

app_name = "reseller_api"

urlpatterns = [
    path("account/", views.account, name="account"),

    path("configs/", views.configs_list, name="configs_list"),
    path("configs/create/", views.configs_create, name="configs_create"),
    path("configs/<int:config_id>/", views.config_detail, name="config_detail"),
    path("configs/<int:config_id>/update/", views.config_update, name="config_update"),
    path("configs/<int:config_id>/toggle/", views.config_toggle, name="config_toggle"),
    path("configs/<int:config_id>/delete/", views.config_delete, name="config_delete"),
]
