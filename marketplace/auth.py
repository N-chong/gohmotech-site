BUYER_GROUP_NAME = "Marketplace Buyers"
FARM_OWNER_GROUP_NAME = "Farm Owners"
FARM_OPERATOR_GROUP_NAME = "Farm Operators"

ROLE_ADMIN = "admin"
ROLE_FARM_OWNER = "farm_owner"
ROLE_FARM_OPERATOR = "farm_operator"
ROLE_MARKETPLACE = "marketplace"


def default_page_name(user):
    """Return the existing home route for an account's trusted system role."""
    role = get_system_role(user)
    if role == ROLE_ADMIN:
        return "iot:dashboard"
    if role in {ROLE_FARM_OWNER, ROLE_FARM_OPERATOR}:
        return "iot:owner_dashboard"
    return "marketplace:landing"


def get_system_role(user):
    """Return the account's highest trusted GoHMotech role."""
    if not getattr(user, "is_authenticated", False):
        return None
    if user.is_staff or user.is_superuser:
        return ROLE_ADMIN
    group_names = set(user.groups.values_list("name", flat=True))
    if FARM_OWNER_GROUP_NAME in group_names:
        return ROLE_FARM_OWNER
    if FARM_OPERATOR_GROUP_NAME in group_names:
        return ROLE_FARM_OPERATOR
    return ROLE_MARKETPLACE


def is_admin(user):
    return get_system_role(user) == ROLE_ADMIN


def is_farm_owner(user):
    return get_system_role(user) == ROLE_FARM_OWNER


def is_farm_operator(user):
    return get_system_role(user) == ROLE_FARM_OPERATOR


def can_manage_farm(user):
    return get_system_role(user) in {ROLE_ADMIN, ROLE_FARM_OWNER}


def has_farm_access(user):
    """Return whether an account may enter the client's smart-farm modules.

    Marketplace capabilities (including future seller approval) are deliberately
    separate from this check. Community sellers must never inherit farm access.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    return get_system_role(user) in {
        ROLE_ADMIN, ROLE_FARM_OWNER, ROLE_FARM_OPERATOR,
    }


def is_marketplace_user(user):
    """Regular marketplace accounts are buyers by default.

    Approved sellers will remain marketplace users and retain buyer features;
    seller approval must not make them farm operators.
    """
    return bool(
        getattr(user, "is_authenticated", False)
        and not has_farm_access(user)
    )


def is_marketplace_buyer(user):
    """Backward-compatible template helper for the former buyer-only role."""
    return is_marketplace_user(user)


def seller_profile_for(user):
    if not getattr(user, "is_authenticated", False):
        return None
    try:
        return user.seller_profile
    except AttributeError:
        return None


def is_approved_seller(user):
    """Return whether a user may operate listings they own.

    Staff operate the original GoHMoTech smart farm and do not pass through the
    community seller-application workflow. Community accounts still require an
    approved profile, which never grants farm access.
    """
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    if can_manage_farm(user):
        return True
    profile = seller_profile_for(user)
    return bool(profile and profile.status == "approved")
