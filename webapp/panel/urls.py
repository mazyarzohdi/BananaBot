from django.urls import path
from . import views

app_name = "panel"

urlpatterns = [
    # Auth
    path("login/",  views.login_view,  name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("auth/webapp/", views.webapp_login, name="webapp_login"),

    # Dashboard
    path("",         views.dashboard, name="dashboard"),
    path("dashboard/", views.dashboard, name="dashboard_alt"),

    # User
    path("services/", views.user_services, name="user_services"),
    path("buy/",      views.user_buy,      name="user_buy"),
    path("wallet/",   views.user_wallet,   name="user_wallet"),

    # Admin — users
    path("admin/users/",                      views.admin_users,       name="admin_users"),
    path("admin/users/<int:telegram_id>/",    views.admin_user_detail, name="admin_user_detail"),

    # Admin — products
    path("admin/products/",               views.admin_products,      name="admin_products"),
    path("admin/products/add/",           views.admin_product_edit,  name="admin_product_add"),
    path("admin/products/<int:product_id>/edit/",   views.admin_product_edit,   name="admin_product_edit"),
    path("admin/products/<int:product_id>/delete/", views.admin_product_delete, name="admin_product_delete"),

    # Admin — panels
    path("admin/panels/",                 views.admin_panels,     name="admin_panels"),
    path("admin/panels/<int:panel_id>/",  views.admin_panel_edit, name="admin_panel_edit"),

    # Admin — payments
    path("admin/payments/",                     views.admin_payments,        name="admin_payments"),
    path("admin/payments/<int:payment_id>/",    views.admin_payment_detail,  name="admin_payment_detail"),
    path("admin/payments/<int:payment_id>/receipt/", views.admin_payment_receipt, name="admin_payment_receipt"),

    # Admin — settings
    path("admin/settings/", views.admin_settings, name="admin_settings"),
]
