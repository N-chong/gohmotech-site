"""Authentication events written to the persistent system audit log."""

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .models import SystemLog
from .system_logging import record_system_log


@receiver(user_logged_in, dispatch_uid="dashboard.system_log.user_logged_in")
def log_user_login(sender, request, user, **kwargs):
    record_system_log(
        event="auth.login_succeeded",
        message=f"User {user.get_username()} signed in.",
        category=SystemLog.CATEGORY_AUTH,
        source="django.auth",
        actor=user,
        request=request,
        status_code=200,
    )


@receiver(user_logged_out, dispatch_uid="dashboard.system_log.user_logged_out")
def log_user_logout(sender, request, user, **kwargs):
    name = user.get_username() if user is not None else "unknown user"
    record_system_log(
        event="auth.logout",
        message=f"User {name} signed out.",
        category=SystemLog.CATEGORY_AUTH,
        source="django.auth",
        actor=user,
        request=request,
        status_code=200,
    )


@receiver(user_login_failed, dispatch_uid="dashboard.system_log.user_login_failed")
def log_user_login_failed(sender, credentials, request, **kwargs):
    attempted_identity = credentials.get("username") or credentials.get("email") or "unknown"
    record_system_log(
        event="auth.login_failed",
        message=f"Failed sign-in attempt for {str(attempted_identity)[:150]}.",
        level=SystemLog.LEVEL_WARNING,
        category=SystemLog.CATEGORY_AUTH,
        source="django.auth",
        request=request,
        status_code=401,
        # Never persist credentials; even this metadata contains no password.
        metadata={"attempted_identity": str(attempted_identity)[:150]},
    )
