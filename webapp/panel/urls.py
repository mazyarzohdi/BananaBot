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
    path("reseller/", views.reseller_panel, name="reseller_panel"),

    # Admin — users
    path("admin/users/",                      views.admin_users,       name="admin_users"),
    path("admin/users/<int:telegram_id>/",    views.admin_user_detail, name="admin_user_detail"),
    path("admin/subscriptions/<int:sub_id>/delete/", views.admin_subscription_delete, name="admin_subscription_delete"),

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

    # Admin — reseller plans
    path("admin/reseller-plans/",                       views.admin_reseller_plans,      name="admin_reseller_plans"),
    path("admin/reseller-plans/add/",                    views.admin_reseller_plan_edit,  name="admin_reseller_plan_add"),
    path("admin/reseller-plans/<int:plan_id>/edit/",     views.admin_reseller_plan_edit,  name="admin_reseller_plan_edit"),
    path("admin/reseller-plans/<int:plan_id>/delete/",   views.admin_reseller_plan_delete, name="admin_reseller_plan_delete"),

    # Admin — resellers review
    path("admin/resellers/",                    views.admin_resellers,       name="admin_resellers"),
    path("admin/resellers/<int:reseller_id>/",  views.admin_reseller_detail, name="admin_reseller_detail"),

    # Admin — settings
    path("admin/settings/", views.admin_settings, name="admin_settings"),
]
